"""Informe de diagnostico exportable en un solo archivo."""

import json
import tarfile
from pathlib import Path

from falso import SistemaFalso
from radio_rtw88 import informe
from radio_rtw88.config import Config
from radio_rtw88.eventos import Bitacora


def test_el_informe_reune_bitacora_legible_resumen_y_evidencia(tmp_path: Path) -> None:
    cfg = Config(estado_dir=str(tmp_path))
    Bitacora(cfg.estado_dir).anotar("wifi", "recuperada_sola", segundos=4.0)
    ruta = informe.generar(SistemaFalso(), cfg)
    assert ruta and ruta.endswith(".tar.gz")
    with tarfile.open(ruta) as tar:
        nombres = tar.getnames()
        bitacora = next(n for n in nombres if n.endswith("bitacora.txt"))
        resumen = next(n for n in nombres if n.endswith("resumen.json"))
        texto = tar.extractfile(bitacora).read().decode()  # type: ignore[union-attr]
        datos = json.loads(tar.extractfile(resumen).read())  # type: ignore[union-attr]
    assert "se recupero sola en 4.0 s" in texto
    assert datos["medida"]["causa"] == "sano" and "ajustes" in datos


def test_conserva_solo_los_ultimos_informes(tmp_path: Path) -> None:
    cfg = Config(estado_dir=str(tmp_path))
    carpeta = tmp_path / "informes"
    carpeta.mkdir()
    for i in range(15):
        (carpeta / f"informe-20260101-0000{i:02d}.tar.gz").write_text("x")
    informe.generar(SistemaFalso(), cfg)
    assert len(list(carpeta.glob("informe-*.tar.gz"))) == informe.GUARDADOS
