"""Patron de intento con alternativa: cada paso corre en try/except y, si falla, lo intenta el siguiente.

Es la regla del proyecto: ninguna funcion importante depende de un solo camino. El primer paso es
el preferido (el mas suave o el mas preciso) y los demas son respaldos cada vez mas contundentes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

log = logging.getLogger(__name__)

Paso = tuple[str, Callable[[], bool]]
# Se llama antes de cada paso: el demonio lo conecta al watchdog de systemd, asi una escalera larga
# demuestra que avanza, y un paso que de verdad se cuelga deja de latir y systemd lo reinicia.


def _sin_latido() -> None:
    return None


latido: Callable[[], object] = _sin_latido


@dataclass(frozen=True)
class Desenlace:
    ok: bool
    paso: str | None  # nombre del paso que lo logro, o None si todos fallaron
    fallidos: tuple[str, ...]


def con_respaldo(tarea: str, pasos: Sequence[Paso]) -> Desenlace:
    """Ejecuta los pasos en orden hasta que uno devuelva True. Nunca propaga excepciones."""
    fallidos: list[str] = []
    for nombre, paso in pasos:
        try:
            latido()
            if paso():
                if fallidos:
                    log.info("%s: lo logro el respaldo '%s' tras %s", tarea, nombre, fallidos)
                return Desenlace(True, nombre, tuple(fallidos))
            log.info("%s: '%s' no lo logro, sigue el respaldo", tarea, nombre)
        except Exception:  # cualquier fallo del paso pasa al siguiente camino
            log.exception("%s: '%s' lanzo una excepcion, sigue el respaldo", tarea, nombre)
        fallidos.append(nombre)
    log.error("%s: fallaron todos los caminos %s", tarea, fallidos)
    return Desenlace(False, None, tuple(fallidos))


def seguro[T](tarea: str, funcion: Callable[[], T], alternativa: Callable[[], T]) -> T:
    """Devuelve funcion(); si lanza, devuelve alternativa(); si esta tambien lanza, propaga."""
    try:
        return funcion()
    except Exception:
        log.exception("%s fallo, uso la alternativa", tarea)
        return alternativa()
