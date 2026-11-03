"""Integracion con systemd y avisos.

sd_notify sin dependencias: READY al arrancar, WATCHDOG en cada vuelta (si el bucle se traba, systemd
reinicia el controlador) y STATUS legible en `systemctl status`. Los avisos usan la politica nocturna
de /usr/local/lib/guardian-aviso.sh (silencio de 22 a 7, critico una vez por hora) y, si falta, el log.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess

log = logging.getLogger(__name__)
AVISO = "/usr/local/lib/guardian-aviso.sh"


def notificar(mensaje: str) -> bool:
    destino = os.environ.get("NOTIFY_SOCKET")
    if not destino:
        return False
    if destino.startswith("@"):  # socket abstracto
        destino = "\0" + destino[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(destino)
            s.sendall(mensaje.encode())
        return True
    except OSError as exc:
        log.warning("sd_notify fallo: %s", exc)
        return False


def avisar(nivel: str, texto: str, nombre: str = "", entorno: str = "") -> None:
    """nivel: critical | recovered | resumen (el resumen diario, sin sonido, solo con red)."""
    nombre = nombre or _equipo["nombre"]
    entorno = entorno or _equipo["entorno"]
    if not os.path.exists(AVISO):
        log.warning("aviso %s sin modulo de avisos: %s", nivel, texto)
        return
    guion = (
        'GUARDIAN_NOMBRE="$3" STATE_DIR=/var/lib/controlador-radio LOG="journalctl -u controlador-radio"; '
        '[ -n "$4" ] && . "$4" 2>/dev/null; . "$0"; '
        'if [ "$1" = resumen ]; then tg_resumen; else tg "$1" "$2"; fi'
    )
    try:
        subprocess.run(
            ["bash", "-c", guion, AVISO, nivel, f"{nombre} WiFi: {texto}", nombre, entorno],
            timeout=30,
            check=False,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("no se pudo enviar el aviso %s (%s): %s", nivel, exc, texto)


_equipo = {"nombre": "servidor", "entorno": ""}


def configurar(nombre: str, entorno: str) -> None:
    """Lo llama el demonio al arrancar con config.nombre y config.aviso_env."""
    _equipo.update(nombre=nombre, entorno=entorno)
