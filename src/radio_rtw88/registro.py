"""Registro persistente: contadores por causa y remedio, crashes del firmware y la ultima medida.

Se guarda en <estado_dir>/estado.json de forma atomica (archivo temporal + rename) para que un corte
de luz nunca deje el archivo a medias. Si no se puede leer o escribir, el controlador sigue igual.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .sondas import Medida

log = logging.getLogger(__name__)
SEMANA = 7 * 86400


class Registro:
    def __init__(self, directorio: str, reloj: Any = time.time) -> None:
        self.ruta = Path(directorio) / "estado.json"
        self.reloj = reloj
        self.datos: dict[str, Any] = {"causas": {}, "remedios": {}, "crashes": [], "medida": None, "mttr": []}
        try:
            self.datos.update(json.loads(self.ruta.read_text()))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("estado.json ilegible (%s): empiezo de cero", exc)

    def _sumar(self, grupo: str, clave: str) -> None:
        self.datos[grupo][clave] = self.datos[grupo].get(clave, 0) + 1

    def causa(self, estado: str, medida: Medida) -> None:
        if estado != "sano":
            self._sumar("causas", estado)
        self.datos["medida"] = asdict(medida) | {"estado": estado, "hora": int(self.reloj())}

    def remedio(self, paso: str | None) -> None:
        self._sumar("remedios", paso or "ninguno_funciono")

    def recuperacion(self, segundos: float) -> None:
        """Guarda los ultimos 50 tiempos de recuperacion (MTTR) en segundos."""
        self.datos["mttr"] = [*self.datos.get("mttr", [])[-49:], round(segundos, 1)]

    def crash(self) -> None:
        ahora = self.reloj()
        self.datos["crashes"] = [t for t in self.datos["crashes"] if ahora - t < SEMANA] + [int(ahora)]

    def crashes_desde(self, segundos: float) -> int:
        return sum(1 for t in self.datos["crashes"] if self.reloj() - t < segundos)

    def guardar(self) -> bool:
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.ruta.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.datos, indent=1, sort_keys=True))
            os.replace(tmp, self.ruta)
            return True
        except OSError as exc:
            log.warning("no se pudo guardar el estado: %s", exc)
            return False
