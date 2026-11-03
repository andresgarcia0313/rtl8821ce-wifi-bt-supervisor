"""Bitacora de eventos de la wifi y del Bluetooth: un JSON por linea en <estado_dir>/eventos.jsonl.

Cada evento dice que paso (falla, crash, remedio, recuperacion), a que equipo (wifi o bt), por que
(la causa diagnosticada) y en que escenario (carga, memoria, temperatura, senal, canal, Bluetooth,
cable USB). Si hubo falla, apunta a la carpeta de evidencia con los registros completos.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
TOPE_BYTES = 5 * 1024 * 1024  # al pasarlo, eventos.jsonl rota a eventos.jsonl.1


class Bitacora:
    def __init__(self, directorio: str) -> None:
        self.ruta = Path(directorio) / "eventos.jsonl"
        self.cerrojo = threading.Lock()  # la escucha del kernel corre en otro hilo

    def anotar(self, equipo: str, tipo: str, **datos: Any) -> dict[str, Any]:
        evento = {"hora": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "equipo": equipo, "tipo": tipo, **datos}
        log.info("evento %s/%s: %s", equipo, tipo, datos.get("causa") or datos.get("detalle") or "")
        try:
            with self.cerrojo:
                self.ruta.parent.mkdir(parents=True, exist_ok=True)
                if self.ruta.exists() and self.ruta.stat().st_size > TOPE_BYTES:
                    os.replace(self.ruta, self.ruta.with_suffix(".jsonl.1"))
                with self.ruta.open("a") as f:
                    f.write(json.dumps(evento, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:  # sin bitacora el controlador sigue: queda en el journal
            log.warning("no se pudo anotar el evento (%s): %s", exc, evento)
        return evento

    def ultimos(self, n: int = 20) -> list[dict[str, Any]]:
        try:
            lineas = self.ruta.read_text().splitlines()[-n:]
        except OSError:
            return []
        eventos = []
        for linea in lineas:
            try:
                eventos.append(json.loads(linea))
            except ValueError:
                continue  # una linea a medias (corte de luz) no impide leer las demas
        return eventos
