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


def ping(s: Sistema, cfg: Config, destino: str) -> bool:
    return s.correr(["ping", "-c1", "-W2", "-I", cfg.iface, destino], tope=5).ok


def debugfs(s: Sistema, cfg: Config) -> str | None:
    """Carpeta rtw88 de debugfs. Depende del phyN, que cambia con cada recarga del modulo."""
    phy = s.leer(f"/sys/class/net/{cfg.iface}/phy80211/name")
    return f"/sys/kernel/debug/ieee80211/{phy.strip()}/rtw88" if phy else None


def debugfs_escribible(s: Sistema) -> bool:
    """Con Secure Boot el kernel entra en lockdown y prohibe escribir en debugfs, incluso a root."""
    modo = s.leer("/sys/kernel/security/lockdown")
    return modo is None or "[none]" in modo


def chip_vivo(s: Sistema, cfg: Config) -> bool:
    """Registros MAC por MMIO; si no hay debugfs, que `iw` todavia vea la interfaz."""
    carpeta = debugfs(s, cfg)
    crudo = s.leer(f"{carpeta}/mac_0") if carpeta else None
    if crudo is None:
        return s.correr(["iw", "dev", cfg.iface, "info"], tope=5).ok
    valores = re.findall(r"\b[0-9a-f]{8}\b", crudo.lower())[1:]  # el primero es la direccion
    return bool(valores) and any(v != "ffffffff" for v in valores)


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


def ap_visible(s: Sistema, cfg: Config) -> bool:
    """Busca el SSID de la conexion en los resultados de escaneo que ya tiene NetworkManager."""
    ssid = s.correr(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", cfg.conexion])
    nombre = ssid.salida.strip() if ssid.ok else cfg.conexion
    lista = s.correr(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "ifname", cfg.iface])
    if lista.ok and nombre in lista.salida.splitlines():
        return True
    escaneo = s.correr(["iw", "dev", cfg.iface, "scan", "dump"], tope=10)
    return escaneo.ok and f"SSID: {nombre}" in escaneo.salida


def medir(s: Sistema, cfg: Config) -> Medida:
    if s.leer(f"/sys/class/net/{cfg.iface}/operstate") is None:
        return Medida(False, False, False, False, False, False)
    asociado, senal, tasa, freq = enlace(s, cfg)
    puerta = ping(s, cfg, cfg.puerta) if asociado else False
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
