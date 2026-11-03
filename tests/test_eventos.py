from pathlib import Path

from falso import SistemaFalso
from radio_rtw88 import evidencia
from radio_rtw88.config import Config
from radio_rtw88.eventos import TOPE_BYTES, Bitacora


def test_bitacora_tolera_lineas_rotas_y_rota_por_tamano(tmp_path: Path) -> None:
    b = Bitacora(str(tmp_path))
    b.anotar("wifi", "falla", causa="zombi")
    with b.ruta.open("a") as f:
        f.write('{"a medias"\n')  # corte de luz a mitad de una linea
    b.anotar("bt", "falla", detalle="x")
    assert [e["equipo"] for e in b.ultimos()] == ["wifi", "bt"]
    b.ruta.write_text("x" * (TOPE_BYTES + 1))
    b.anotar("wifi", "remedio")
    assert b.ruta.with_suffix(".jsonl.1").exists() and len(b.ultimos()) == 1


def test_evidencia_guarda_registros_y_poda_las_viejas(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cfg = Config(estado_dir=str(tmp_path))
    monkeypatch.setattr(evidencia, "MAX_CARPETAS", 2)
    rutas = []
    for i in range(3):
        carpeta = evidencia.capturar(SistemaFalso(), cfg, f"prueba{i}")
        assert carpeta is not None
        rutas.append(Path(carpeta))
    vivas = sorted(p.name for p in (tmp_path / "eventos").iterdir())
    assert len(vivas) == 2 and "kernel.txt" in {f.name for f in rutas[-1].iterdir()}


def test_cable_usb_por_driver_y_no_por_el_nombre_enx(tmp_path: Path) -> None:
    from radio_rtw88.escenario import anclaje_usb

    def interfaz(nombre: str, driver: str) -> None:
        (tmp_path / "drv" / driver).mkdir(parents=True, exist_ok=True)
        (tmp_path / "net" / nombre / "device").mkdir(parents=True)
        (tmp_path / "net" / nombre / "device" / "driver").symlink_to(tmp_path / "drv" / driver)

    interfaz("enx020000000002", "btusb")  # el enlace Bluetooth renombrado por udev
    assert not anclaje_usb(str(tmp_path / "net"))
    interfaz("enx020000000003", "rndis_host")  # el anclaje del celular por cable
    assert anclaje_usb(str(tmp_path / "net"))
    assert not anclaje_usb(str(tmp_path / "no-existe"))
