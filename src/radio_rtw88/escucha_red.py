"""Escucha en vivo de los eventos de la wifi que publica el kernel (nl80211), como el monitor de enlace de
Android y ChromeOS: desconexion, desautenticacion, perdida de balizas, paquetes sin confirmar y senal bajo
el umbral avisan al controlador en el mismo segundo, sin esperar la revision periodica.

`iw event` lee el canal de eventos de nl80211 sin gastar CPU mientras no pase nada. El umbral de senal
se arma con `iw dev <if> cqm rssi <umbral> <histeresis>`: el kernel avisa al cruzarlo, sin medir a cada rato.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from collections.abc import Callable

from .config import Config
from .intentos import resiste, valor
from .sistema import Sistema

log = logging.getLogger(__name__)
FALLA = re.compile(
    r"disconnected|deauth|disassoc|beacon loss|didn't ACK|RSSI went below|connection quality monitor"
    r".*(below|loss)",
    re.I,
)
VUELTA = re.compile(r": connected to |RSSI went above", re.I)


@resiste(valor(False))
def armar_umbral(s: Sistema, cfg: Config) -> bool:
    """El kernel avisa cuando la senal cruza el umbral (con histeresis para no avisar en cada vaiven)."""
    orden = ["iw", "dev", cfg.iface, "cqm", "rssi", str(cfg.umbral_senal), str(cfg.histeresis_senal)]
    return s.correr(orden, tope=5).ok


@resiste(valor(None))
def clasificar(linea: str, iface: str) -> str | None:
    """'falla', 'vuelta' o None (eventos de otra interfaz o sin interes, como el inicio de un escaneo)."""
    if f"{iface} " not in linea:
        return None
    if FALLA.search(linea):
        return "falla"
    return "vuelta" if VUELTA.search(linea) else None


class EscuchaRed:
    def __init__(self, cfg: Config, al_evento: Callable[[str, str], None]) -> None:
        self.cfg, self.al_evento = cfg, al_evento
        self.hilo = threading.Thread(target=self._correr, name="nl80211", daemon=True)

    @resiste(valor(None))
    def procesar(self, linea: str) -> str | None:
        tipo = clasificar(linea, self.cfg.iface)
        if tipo:
            self.al_evento(tipo, linea.strip()[-200:])
        return tipo

    def _correr(self) -> None:
        for intento in range(3):  # si iw muere, se relanza; sin iw quedan las revisiones periodicas
            try:
                p = subprocess.Popen(["iw", "event", "-t"], stdout=subprocess.PIPE, text=True)
                assert p.stdout is not None
                for linea in p.stdout:
                    self.procesar(linea)
            except Exception:
                log.exception("escucha de eventos de la wifi fallo (intento %d)", intento + 1)
        log.error("sin escucha de eventos de la wifi: quedan solo las revisiones periodicas")

    @resiste(valor(None))
    def iniciar(self) -> None:
        self.hilo.start()
