"""Escenario de un evento: foto rapida de lo que pasaba alrededor de una falla (cada dato es opcional)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .config import Config
from .intentos import resiste, valor
from .sistema import Sistema


def _leer(ruta: str) -> str:
    try:
        return Path(ruta).read_text().strip()
    except OSError:
        return ""


ESTACION = {
    "balizas_perdidas": r"beacon loss:\s*(\d+)",
    "tx_fallidos": r"tx failed:\s*(\d+)",
    "tx_reintentos": r"tx retries:\s*(\d+)",
    "rx_descartes": r"rx drop misc:\s*(\d+)",
    "senal_media": r"signal avg:\s*(-?\d+)",
}
ANCLAJE = frozenset({"rndis_host", "cdc_ether", "cdc_ncm", "ipheth"})


@resiste(valor(None))
def interfaz_anclaje(red: str = "/sys/class/net") -> str | None:
    """Interfaz del cable del celular, reconocida por su driver: el enlace Bluetooth tambien se llama
    enx<mac> (udev) y Android cambia la MAC en cada anclaje."""
    try:
        for n in sorted(os.listdir(red)):
            if os.path.basename(os.path.realpath(f"{red}/{n}/device/driver")) in ANCLAJE:
                return n
    except OSError:
        pass
    return None


@resiste(valor(False))
def anclaje_usb(red: str = "/sys/class/net") -> bool:
    return interfaz_anclaje(red) is not None


@resiste(lambda *_a, **_k: {})
def escenario(s: Sistema, cfg: Config) -> dict[str, Any]:
    """Foto rapida de lo que pasaba alrededor de la falla (cada dato es opcional)."""
    datos: dict[str, Any] = {"carga": _leer("/proc/loadavg")}
    memoria = re.search(r"MemAvailable:\s+(\d+)", _leer("/proc/meminfo"))
    datos["memoria_libre_mb"] = int(memoria.group(1)) // 1024 if memoria else None
    io = re.search(r"some avg10=([\d.]+)", _leer("/proc/pressure/io"))
    datos["presion_io_10s"] = float(io.group(1)) if io else None
    datos["encendido_s"] = (
        int(float(_leer("/proc/uptime").split()[0] or 0)) if _leer("/proc/uptime") else None
    )
    enlace = s.correr(["iw", "dev", cfg.iface, "link"], tope=5).salida
    for clave, patron in (("bssid", r"Connected to (\S+)"), ("frecuencia_mhz", r"freq:\s*([\d.]+)")):
        hallado = re.search(patron, enlace)
        datos[clave] = hallado.group(1) if hallado else None
    # contadores de la estacion: las caidas "asociado sin trafico" acaban en desasociacion por balizas
    estacion = s.correr(["iw", "dev", cfg.iface, "station", "dump"], tope=5).salida
    for clave, patron in ESTACION.items():
        hallado = re.search(patron, estacion)
        datos[clave] = int(hallado.group(1)) if hallado else None
    datos["bluetooth_conectados"] = len(
        s.correr(["bluetoothctl", "devices", "Connected"], tope=5).salida.splitlines()
    )
    datos["cable_usb"] = anclaje_usb()
    ruta = re.search(r"dev (\S+)", s.correr(["ip", "route", "get", "1.1.1.1"], tope=5).salida)
    datos["salida_internet"] = ruta.group(1) if ruta else None  # por donde sale el trafico ahora
    # un portatil-servidor sin cargador cambia de perfil de energia (TLP) y termina apagandose
    datos["cargador"] = _leer("/sys/class/power_supply/AC/online") or None
    datos["bateria"] = _leer("/sys/class/power_supply/BAT0/capacity") or None
    return datos
