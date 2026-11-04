"""Ajustes del driver vigilados, como la pestana "Opciones avanzadas" del driver Realtek en Windows.

Ahorro de energia de la wifi apagado (otro programa, como TLP, puede volver a encenderlo) y Bluetooth
USB siempre encendido (equivale a quitar "Permitir que el equipo apague este dispositivo"): la
suspension automatica de btusb es una causa conocida de que el Bluetooth Realtek deje de responder.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from . import bluetooth
from .config import Config
from .intentos import resiste, valor
from .sistema import Sistema

log = logging.getLogger(__name__)
CADA_AJUSTES = 300  # segundos entre revisiones de los ajustes
PARAMETROS = ("disable_aspm", "disable_lps_deep", "disable_msi")


@resiste(valor(None))
def ahorro_wifi(s: Sistema, cfg: Config) -> str | None:
    r = s.correr(["iw", "dev", cfg.iface, "get", "power_save"], tope=5)
    hallado = re.search(r"Power save:\s*(\w+)", r.salida) if r.ok else None
    return hallado.group(1) if hallado else None


@resiste(valor(False))
def apagar_ahorro_wifi(s: Sistema, cfg: Config) -> bool:
    return s.correr(["iw", "dev", cfg.iface, "set", "power_save", "off"], tope=5).ok


@resiste(valor(None))
def ruta_energia_bt(s: Sistema, cfg: Config) -> str | None:
    disp = bluetooth.dispositivo_usb(s, cfg)
    return f"{bluetooth.USB}/{disp}/power/control" if disp else None


@resiste(valor(None))
def energia_bt(s: Sistema, cfg: Config) -> str | None:
    """'on': siempre encendido; 'auto': el kernel lo suspende tras unos segundos sin uso."""
    ruta = ruta_energia_bt(s, cfg)
    leido = s.leer(ruta) if ruta else None
    return leido.strip() if leido else None


@resiste(valor(None))
def leer_todos(s: Sistema, cfg: Config) -> dict[str, str | None]:
    """Cada opcion al estilo Windows con su valor en Linux (comando `controlador-radio ajustes`)."""
    pais = re.search(r"country (\w+)", s.correr(["iw", "reg", "get"], tope=5).salida)
    datos: dict[str, str | None] = {
        "ahorro_energia_wifi": ahorro_wifi(s, cfg),
        "bluetooth_suspension_usb": energia_bt(s, cfg),
        "pais_radio": pais.group(1) if pais else None,
    }
    for nombre in PARAMETROS:
        for modulo in ("rtw88_pci", "rtw88_core"):
            leido = s.leer(f"/sys/module/{modulo}/parameters/{nombre}")
            if leido is not None:
                datos[nombre] = leido.strip()
    return datos


class Ajustes:
    def __init__(
        self,
        s: Sistema,
        cfg: Config,
        anotar: Callable[..., object] = lambda *a, **k: None,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.s, self.cfg, self.anotar, self.reloj = s, cfg, anotar, reloj
        self.ultimo = -1e9

    @resiste(lambda *_a, **_k: [])
    def vigilar(self) -> list[str]:
        """Corrige lo que se haya desviado y lo anota; en modo observar solo lo anota."""
        if not self.cfg.ajustes or self.reloj() - self.ultimo < CADA_AJUSTES:
            return []
        self.ultimo = self.reloj()
        desviados = []
        if ahorro_wifi(self.s, self.cfg) == "on":
            desviados.append("ahorro_energia_wifi")
        if self.cfg.bluetooth and energia_bt(self.s, self.cfg) == "auto":
            desviados.append("bluetooth_suspension_usb")
        for nombre in desviados:
            ok = self.cfg.modo == "actuar" and self.corregir(nombre)
            log.warning("ajuste '%s' desviado; corregido: %s", nombre, ok)
            self.anotar("ajuste", ajuste=nombre, corregido=ok)
        return desviados

    @resiste(valor(False))
    def corregir(self, nombre: str) -> bool:
        if nombre == "ahorro_energia_wifi":
            return apagar_ahorro_wifi(self.s, self.cfg)
        ruta = ruta_energia_bt(self.s, self.cfg)
        return ruta is not None and self.s.escribir(ruta, "on")
