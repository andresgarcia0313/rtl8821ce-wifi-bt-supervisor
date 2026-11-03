"""Evidencia de una falla: registros completos en <estado_dir>/eventos/<fecha>-<motivo>/.

Guarda lo necesario para saber por que fallo sin tener que reproducirlo: kernel, NetworkManager,
wpa_supplicant, Bluetooth, estado del enlace y de la estacion, PCI (errores AER y estado del enlace
PCIe), firmware, presion del sistema y el volcado del firmware (devcoredump), que el kernel borra a
los 5 minutos. Cada orden lleva tope; la carpeta se poda para no llenar el disco.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from . import intentos
from .config import Config
from .ordenes_evidencia import registros, volatil
from .sistema import Sistema

log = logging.getLogger(__name__)
MAX_CARPETAS = 60
MAX_BYTES = 300 * 1024 * 1024
TOPE_ARCHIVO = 400 * 1024  # cada registro se recorta a sus ultimos 400 KB


def _volcados(s: Sistema, carpeta: Path) -> int:
    """Copia comprimidos los devcoredump presentes (rtw88 y btusb dejan uno al fallar)."""
    try:
        presentes = sorted(Path("/sys/class/devcoredump").glob("devcd*/data"))
    except OSError:
        return 0
    for i, data in enumerate(presentes):
        destino = carpeta / f"devcoredump-{i}.bin.gz"
        s.correr(
            ["sh", "-c", 'timeout -s KILL 30 cat "$1" | gzip -c > "$2"', "_", str(data), str(destino)], 40
        )
    return len(presentes)


def _podar(raiz: Path) -> None:
    carpetas = sorted(p for p in raiz.iterdir() if p.is_dir())
    total = sum(f.stat().st_size for p in carpetas for f in p.iterdir())
    while carpetas and (len(carpetas) > MAX_CARPETAS or total > MAX_BYTES):
        vieja = carpetas.pop(0)
        total -= sum(f.stat().st_size for f in vieja.iterdir())
        shutil.rmtree(vieja, ignore_errors=True)


def _escribir(s: Sistema, carpeta: Path, tabla: dict[str, list[list[str]]]) -> None:
    for archivo, lista in tabla.items():
        partes = []
        for orden in lista:
            intentos.latido()
            r = s.correr(orden, tope=10)
            partes.append(f"$ {' '.join(orden)}  (rc={r.rc})\n{r.salida}{r.error}")
        (carpeta / archivo).write_text("\n".join(partes)[-TOPE_ARCHIVO:])


def capturar(s: Sistema, cfg: Config, motivo: str, con_registros: bool = True) -> str | None:
    """Guarda la evidencia y devuelve la carpeta; si algo falla guarda lo que pudo, nunca lanza.
    con_registros=False deja el journal para completar() despues del remedio."""
    raiz = Path(cfg.estado_dir) / "eventos"
    carpeta = raiz / f"{time.strftime('%Y%m%d-%H%M%S')}-{motivo}"
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        volcados = _volcados(s, carpeta)  # primero: el kernel los borra solos
        _escribir(s, carpeta, volatil(cfg))
        if con_registros:
            _escribir(s, carpeta, registros())
        log.info("evidencia en %s (%d volcados de firmware)", carpeta, volcados)
        _podar(raiz)
        return str(carpeta)
    except OSError as exc:
        log.warning("evidencia incompleta en %s: %s", carpeta, exc)
        return str(carpeta) if carpeta.exists() else None


def completar(s: Sistema, carpeta: str | None) -> None:
    """Agrega los registros del journal a una evidencia tomada sin ellos (cubren los ultimos 15 min)."""
    if not carpeta or (Path(carpeta) / "kernel-radio.txt").exists():
        return
    try:
        _escribir(s, Path(carpeta), registros())
    except OSError as exc:
        log.warning("no se pudieron completar los registros de %s: %s", carpeta, exc)
