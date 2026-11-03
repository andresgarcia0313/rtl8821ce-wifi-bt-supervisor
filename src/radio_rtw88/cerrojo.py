"""Cerrojo entre procesos: un solo actor a la vez sobre la tarjeta (demonio, `reparar`, `probar`, `bt`).

Usa flock sobre un archivo de /run/lock: el kernel lo suelta solo si el proceso muere, asi un cierre
abrupto nunca deja la tarjeta bloqueada para siempre.
"""

from __future__ import annotations

import fcntl
import logging
import os
from collections.abc import Generator
from contextlib import contextmanager

log = logging.getLogger(__name__)
RUTA = "/run/lock/controlador-radio.lock"


@contextmanager
def exclusivo(esperar: bool, ruta: str = RUTA) -> Generator[bool]:
    """Entrega True si se obtuvo el cerrojo. Sin poder abrir el archivo entrega True: mejor actuar."""
    try:
        fd = os.open(ruta, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        log.warning("sin cerrojo (%s): sigo sin exclusion", exc)
        yield True
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if esperar else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("otro proceso esta actuando sobre la tarjeta: esta vez no actuo")
            yield False
            return
        yield True
    finally:
        os.close(fd)  # cerrar el descriptor suelta el flock
