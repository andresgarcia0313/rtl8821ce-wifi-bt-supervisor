"""Sondas: miden cada capa por separado y siempre por la interfaz wifi (nunca por el cable USB).

Cada sonda devuelve un valor simple y no lanza excepciones; si su metodo preferido falla, prueba otro.
rtw88 no tiene lectura de temperatura como iwlwifi: la prueba de vida del chip es leer sus registros
MAC por MMIO (debugfs `mac_0`, modo 0444, permitido aun con el kernel en lockdown por Secure Boot).
Un chip caido del bus PCI devuelve 0xffffffff en todos los registros.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Config
from .intentos import resiste, valor
from .sistema import Sistema


@dataclass(frozen=True)
class Medida:
    interfaz: bool  # existe la interfaz del kernel
    firmware: bool  # el chip responde (registros por MMIO; sin debugfs, `iw info`)
    asociado: bool  # hay enlace con un punto de acceso
    ap_visible: bool  # el SSID aparece en el ultimo escaneo
    puerta: bool  # la puerta de enlace responde por la wifi
    internet: bool  # internet responde por la wifi
    senal: int | None = None  # dBm
    tasa_tx: float | None = None  # Mbit/s
    frecuencia: int | None = None  # MHz: 2,4 o 5 GHz
    apagada: bool = False  # alguien apago la radio a proposito (rfkill): no se repara


@resiste(valor(False))
def apagada_a_proposito(s: Sistema, tipo: str) -> bool:
    """Interruptor de radio (rfkill) en "apagado" por software o por la tecla del equipo."""
    for nombre in s.listar("/sys/class/rfkill"):
        base = f"/sys/class/rfkill/{nombre}"
        bloqueo = (s.leer(f"{base}/soft") or "") + (s.leer(f"{base}/hard") or "")
        if (s.leer(f"{base}/type") or "").strip() == tipo and "1" in bloqueo:
            return True
    return False


@resiste(valor(False))
def ping(s: Sistema, cfg: Config, destino: str) -> bool:
    return s.correr(["ping", "-c1", "-W2", "-I", cfg.iface, destino], tope=5).ok


@resiste(valor(False))
def arp(s: Sistema, cfg: Config, destino: str) -> bool:
    """Pregunta por ARP quien tiene la direccion del router (como el monitor de enlace de ChromeOS): un
    router ocupado puede ignorar el ping y aun asi contestar ARP, que es lo que prueba el enlace."""
    return s.correr(["arping", "-c1", "-w2", "-I", cfg.iface, destino], tope=5).ok


def router_responde(s: Sistema, cfg: Config) -> bool:
    return ping(s, cfg, cfg.puerta) or arp(s, cfg, cfg.puerta)


@resiste(valor(None))
def debugfs(s: Sistema, cfg: Config) -> str | None:
    """Carpeta rtw88 de debugfs. Depende del phyN, que cambia con cada recarga del modulo."""
    phy = s.leer(f"/sys/class/net/{cfg.iface}/phy80211/name")
    return f"/sys/kernel/debug/ieee80211/{phy.strip()}/rtw88" if phy else None


@resiste(valor(False))
def debugfs_escribible(s: Sistema) -> bool:
    """Con Secure Boot el kernel entra en lockdown y prohibe escribir en debugfs, incluso a root."""
    modo = s.leer("/sys/kernel/security/lockdown")
    return modo is None or "[none]" in modo


@resiste(valor(True))
def chip_vivo(s: Sistema, cfg: Config) -> bool:
    """Registros MAC por MMIO; si no hay debugfs, que `iw` todavia vea la interfaz."""
    carpeta = debugfs(s, cfg)
    crudo = s.leer(f"{carpeta}/mac_0") if carpeta else None
    if crudo is None:
        return s.correr(["iw", "dev", cfg.iface, "info"], tope=5).ok
    valores = re.findall(r"\b[0-9a-f]{8}\b", crudo.lower())[1:]  # el primero es la direccion
    return bool(valores) and any(v != "ffffffff" for v in valores)


def _operstate_up(s: Sistema, cfg: Config) -> bool:
    return (s.leer(f"/sys/class/net/{cfg.iface}/operstate") or "").strip() == "up"


def _enlace_por_operstate(s: Sistema, cfg: Config) -> tuple[bool, int | None, float | None, int | None]:
    """Si leer `iw link` falla, el estado de la interfaz dice igual si hay asociacion (wifi 'up')."""
    return _operstate_up(s, cfg), None, None, None


@resiste(_enlace_por_operstate)
def enlace(s: Sistema, cfg: Config) -> tuple[bool, int | None, float | None, int | None]:
    r = s.correr(["iw", "dev", cfg.iface, "link"], tope=5)
    if not r.ok or "Connected to" not in r.salida:
        return False, None, None, None
    senal = re.search(r"signal:\s*(-?\d+)", r.salida)
    tasa = re.search(r"tx bitrate:\s*([\d.]+)", r.salida)
    freq = re.search(r"freq:\s*(\d+)", r.salida)
    return (
        True,
        int(senal.group(1)) if senal else None,
        float(tasa.group(1)) if tasa else None,
        int(freq.group(1)) if freq else None,
    )


@resiste(valor(True))
def ap_visible(s: Sistema, cfg: Config) -> bool:
    """Busca el SSID de la conexion en los resultados de escaneo que ya tiene NetworkManager."""
    ssid = s.correr(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", cfg.conexion])
    nombre = ssid.salida.strip() if ssid.ok else cfg.conexion
    lista = s.correr(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "ifname", cfg.iface])
    if lista.ok and nombre in lista.salida.splitlines():
        return True
    escaneo = s.correr(["iw", "dev", cfg.iface, "scan", "dump"], tope=10)
    return escaneo.ok and f"SSID: {nombre}" in escaneo.salida


def _medida_minima(s: Sistema, cfg: Config) -> Medida:
    """Medida de emergencia: solo lo imprescindible y el chip se da por vivo (no se toca a ciegas)."""
    presente = s.leer(f"/sys/class/net/{cfg.iface}/operstate") is not None
    asociado = presente and _operstate_up(s, cfg)
    internet = asociado and any(ping(s, cfg, d) for d in cfg.internet)
    return Medida(presente, True, asociado, True, asociado and router_responde(s, cfg), internet)


@resiste(_medida_minima)
def medir(s: Sistema, cfg: Config) -> Medida:
    if apagada_a_proposito(s, "wlan"):
        return Medida(True, True, False, False, False, False, apagada=True)
    if s.leer(f"/sys/class/net/{cfg.iface}/operstate") is None:
        return Medida(False, False, False, False, False, False)
    asociado, senal, tasa, freq = enlace(s, cfg)
    puerta = router_responde(s, cfg) if asociado else False
    internet = asociado and any(ping(s, cfg, d) for d in cfg.internet)  # cada destino respalda al anterior
    return Medida(
        interfaz=True,
        firmware=chip_vivo(s, cfg),
        asociado=asociado,
        ap_visible=True if asociado else ap_visible(s, cfg),
        puerta=puerta,
        internet=internet,
        senal=senal,
        tasa_tx=tasa,
        frecuencia=freq,
    )
