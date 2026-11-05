"""Informe de diagnostico exportable, como los informes de comentarios de ChromeOS: un solo archivo con
la evidencia de ahora, la bitacora en frases sencillas, los ajustes y la ultima medida, para revisar un
defecto o compartirlo. Queda en <estado_dir>/informes/ con permisos solo para root (lleva datos de la red).
"""

from __future__ import annotations

import json
import logging
import tarfile
import time
from dataclasses import asdict
from pathlib import Path

from . import ajustes, evidencia, relato, sondas
from .config import Config
from .diagnostico import diagnosticar
from .eventos import Bitacora
from .intentos import resiste, valor
from .registro import Registro
from .sistema import Sistema

log = logging.getLogger(__name__)
EVENTOS = 300  # eventos de la bitacora que entran al informe


@resiste(valor(None))
def generar(s: Sistema, cfg: Config) -> str | None:
    carpeta = evidencia.capturar(s, cfg, "informe")
    if carpeta is None:
        return None
    base = Path(carpeta)
    eventos = Bitacora(cfg.estado_dir).ultimos(EVENTOS)
    (base / "bitacora.txt").write_text("\n".join(relato.linea(e) for e in eventos) + "\n")
    m = sondas.medir(s, cfg)
    resumen = {
        "medida": asdict(m) | {"causa": str(diagnosticar(m))},
        "ajustes": ajustes.leer_todos(s, cfg),
        "contadores": Registro(cfg.estado_dir).datos,
        "configuracion": asdict(cfg),
    }
    (base / "resumen.json").write_text(json.dumps(resumen, indent=1, ensure_ascii=False, default=str))
    salida = Path(cfg.estado_dir) / "informes" / f"informe-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    salida.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(salida, "w:gz") as tar:
        tar.add(base, arcname=salida.name.removesuffix(".tar.gz"))
    log.info("informe en %s", salida)
    return str(salida)
