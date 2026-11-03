"""Demonio: repite la vuelta del controlador. Cada vuelta va en try y su except aplica un respaldo minimo.

El watchdog de systemd recibe un latido por vuelta y por cada paso de recuperacion: si algo se cuelga
de verdad, deja de latir y systemd reinicia el demonio; si falla seguido, entra el guardian anterior.
"""

from __future__ import annotations

import logging
import sys

from . import intentos, servicio
from .config import Config
from .principal import Controlador
from .sistema import Sistema

log = logging.getLogger(__name__)
MAX_ERRORES = 20  # vueltas seguidas con excepcion antes de salir y dejar que systemd decida


def bucle(c: Controlador) -> int:
    intentos.latido = lambda: servicio.notificar("WATCHDOG=1")
    c.escucha.iniciar()
    servicio.notificar("READY=1")
    errores = 0
    while errores < MAX_ERRORES:
        try:
            estado: str = c.vuelta()
            c.vigilar_bt()
            errores = 0
        except Exception:
            errores += 1
            log.exception("vuelta fallida %d/%d: aplico el respaldo minimo", errores, MAX_ERRORES)
            estado = intentos.seguro("respaldo minimo", c.respaldo_minimo, lambda: "error interno")
        c.registro.guardar()
        servicio.notificar(f"WATCHDOG=1\nSTATUS=wifi {estado}, fallas {c.fallas}, modo {c.cfg.modo}")
        c.despertar.wait(c.cfg.intervalo)
        c.despertar.clear()
    log.critical("demasiadas vueltas fallidas: salgo para que systemd me reinicie")
    return 1


def main(s: Sistema, cfg: Config) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(name)s: %(message)s")
    servicio.configurar(cfg.nombre, cfg.aviso_env)
    return bucle(Controlador(s, cfg))
