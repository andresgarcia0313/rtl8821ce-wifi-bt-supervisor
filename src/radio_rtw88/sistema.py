"""Acceso al sistema operativo: ordenes externas y escritura en /sys sin que nada lance excepciones.

Todo el controlador pasa por aqui, asi las pruebas sustituyen el sistema real por uno falso.
Regla anticongelamiento: nada que toque el hardware corre dentro de este proceso. Ordenes, escrituras
en /sys y lecturas de debugfs van en un proceso hijo con tope; si el hardware las cuelga (estado D),
queda atrapado el hijo y el controlador sigue vivo, avisando a systemd y probando otro camino.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)
TOPE_SYS = 15  # segundos maximos para una operacion en /sys antes de abandonarla


@dataclass(frozen=True)
class Resultado:
    rc: int
    salida: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.rc == 0


class Sistema(Protocol):
    def correr(self, orden: list[str], tope: float = 20) -> Resultado: ...
    def escribir(self, ruta: str, texto: str) -> bool: ...
    def leer(self, ruta: str) -> str | None: ...
    def dormir(self, segundos: float) -> None: ...
    def leer_enlace(self, ruta: str) -> str | None: ...
    def listar(self, carpeta: str) -> list[str]: ...


class SistemaReal:
    """Implementacion real. Cada metodo atrapa su error y lo convierte en un resultado fallido."""

    def correr(self, orden: list[str], tope: float = 20) -> Resultado:
        try:
            p = subprocess.run(orden, capture_output=True, text=True, timeout=tope, check=False)
            return Resultado(p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired:
            log.warning("tope de %ss agotado: %s", tope, " ".join(orden))
            return Resultado(124, error="timeout")
        except OSError as exc:  # orden inexistente o sin permiso
            log.warning("no se pudo ejecutar %s: %s", orden[0], exc)
            return Resultado(127, error=str(exc))

    def escribir(self, ruta: str, texto: str) -> bool:
        if ruta.startswith("/sys/"):
            orden = [
                "timeout",
                "-s",
                "KILL",
                str(TOPE_SYS),
                "sh",
                "-c",
                'printf %s "$1" > "$2"',
                "_",
                texto,
                ruta,
            ]
            return self.correr(orden, tope=TOPE_SYS + 5).ok
        try:
            Path(ruta).write_text(texto)
            return True
        except OSError as exc:
            log.warning("no se pudo escribir %s: %s", ruta, exc)
            return False

    def leer(self, ruta: str) -> str | None:
        if ruta.startswith("/sys/kernel/debug/"):  # debugfs espera al firmware: puede bloquearse
            r = self.correr(["timeout", "-s", "KILL", str(TOPE_SYS), "cat", ruta], tope=TOPE_SYS + 5)
            return r.salida if r.ok else None
        try:
            return Path(ruta).read_text()
        except OSError:
            return None

    def dormir(self, segundos: float) -> None:
        time.sleep(segundos)

    def leer_enlace(self, ruta: str) -> str | None:
        """Destino absoluto de un enlace de /sys (dispositivo o driver); None si no existe."""
        try:
            return os.path.realpath(ruta, strict=True)
        except OSError:
            return None

    def listar(self, carpeta: str) -> list[str]:
        try:
            return sorted(os.listdir(carpeta))
        except OSError:
            return []
