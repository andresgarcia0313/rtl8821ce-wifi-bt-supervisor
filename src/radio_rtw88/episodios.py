"""Episodios: une la bitacora (que paso, por que, en que escenario) con la evidencia (los registros).

Una falla nueva de la wifi, un error del kernel o una falla del Bluetooth guardan evidencia una sola
vez por episodio; el remedio y la recuperacion se anotan apuntando a esa misma carpeta.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import asdict
from typing import Any

from . import evidencia
from .config import Config
from .escenario import escenario
from .eventos import Bitacora
from .intentos import Desenlace, seguro
from .sistema import Sistema
from .sondas import Medida

log = logging.getLogger(__name__)
CADA_EVIDENCIA = 600.0


class Episodios:
    def __init__(self, s: Sistema, cfg: Config) -> None:
        self.s, self.cfg = s, cfg
        self.bitacora = Bitacora(cfg.estado_dir)
        self.carpeta: str | None = None  # evidencia de la falla de wifi en curso
        self.del_kernel: deque[tuple[str, str]] = deque(maxlen=20)  # lo llena el hilo de la escucha
        self.cerrojo = threading.Lock()
        self.ultima_evidencia: dict[str, float] = {}  # equipo -> hora de la ultima evidencia por el kernel

    def _anotar(
        self, equipo: str, tipo: str, motivo: str | None, rapido: bool = False, **datos: Any
    ) -> str | None:
        """Anota el evento con su escenario y, si hay motivo, captura evidencia (rapido: sin journal,
        para no retrasar el remedio; se completa despues). Nunca lanza."""

        def hacer() -> str | None:
            carpeta = evidencia.capturar(self.s, self.cfg, motivo, not rapido) if motivo else None
            esc = seguro("escenario", lambda: escenario(self.s, self.cfg), dict)
            self.bitacora.anotar(equipo, tipo, escenario=esc, evidencia=carpeta, **datos)
            return carpeta

        return seguro(f"evento {equipo}/{tipo}", hacer, lambda: None)

    def kernel(self, equipo: str, linea: str) -> None:
        """Lo llama la escucha del kernel desde su hilo: solo encola, el bucle principal lo atiende."""
        with self.cerrojo:
            self.del_kernel.append((equipo, linea))

    def atender_kernel(self) -> None:
        while True:
            with self.cerrojo:
                if not self.del_kernel:
                    return
                equipo, linea = self.del_kernel.popleft()
            # una evidencia completa por equipo cada CADA_EVIDENCIA s; las demas lineas solo se anotan, asi un
            # chip que repite un aviso no llena las carpetas ni hace podar la evidencia de otras fallas
            ahora = time.monotonic()
            nueva = ahora - self.ultima_evidencia.get(equipo, -1e9) >= CADA_EVIDENCIA
            if nueva:
                self.ultima_evidencia[equipo] = ahora
            self._anotar(equipo, "error_kernel", f"{equipo}-kernel" if nueva else None, detalle=linea)

    def falla(self, causa: str, m: Medida, crashes_24h: int) -> None:
        self.carpeta = self._anotar(
            "wifi",
            "falla",
            f"wifi-{causa}",
            True,
            causa=causa,
            medida=asdict(m),
            crashes_firmware_24h=crashes_24h,
        )

    def remedio(self, causa: str, d: Desenlace, segundos: float) -> None:
        seguro("completar evidencia", lambda: evidencia.completar(self.s, self.carpeta), lambda: None)
        self._anotar(
            "wifi",
            "remedio",
            None,
            causa=causa,
            paso=d.paso,
            ok=d.ok,
            fallidos=list(d.fallidos),
            segundos=round(segundos, 1),
            evidencia_falla=self.carpeta,
        )

    def recuperada_sola(self, revisiones: int, segundos: float) -> None:
        seguro("completar evidencia", lambda: evidencia.completar(self.s, self.carpeta), lambda: None)
        self._anotar(
            "wifi",
            "recuperada_sola",
            None,
            revisiones=revisiones,
            segundos=round(segundos, 1),
            evidencia_falla=self.carpeta,
        )
        self.carpeta = None

    def bt(self, tipo: str, detalle: str, evidencia_bt: bool = False) -> None:
        self._anotar("bt", tipo, "bt-falla" if evidencia_bt else None, detalle=detalle)
