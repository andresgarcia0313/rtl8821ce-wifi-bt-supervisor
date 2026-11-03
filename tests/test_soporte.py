import os
import socket
import time
from pathlib import Path

import pytest

from radio_rtw88 import cerrojo, config, servicio
from radio_rtw88.config import Config
from radio_rtw88.kmsg import Escucha
from radio_rtw88.registro import Registro
from radio_rtw88.sistema import SistemaReal
from radio_rtw88.sondas import Medida

CRASH = "rtw_8821ce 0000:02:00.0: firmware crash, start reset and recover"


def test_escucha_separa_wifi_y_bluetooth_y_respeta_el_silencio() -> None:
    vistos: list[tuple[str, str]] = []
    e = Escucha(lambda equipo, linea: vistos.append((equipo, linea)), reloj=lambda: 100.0)
    assert e.procesar(CRASH) and not e.procesar(
        "rtw_8821ce 0000:02:00.0: Firmware version 24.11.0, H2C version 12"
    )
    assert e.procesar("Bluetooth: hci0: command 0x0c03 tx timeout")
    e.silenciar(10)
    assert not e.procesar(CRASH)  # el silencio tapa los crashes que provocan los remedios
    assert e.procesar("Bluetooth: hci0: Hardware error 0x0b")  # el de la wifi no tapa los del Bluetooth
    e.silenciar_bt(10)
    assert not e.procesar("Bluetooth: hci0: urb failed to resubmit (2)")  # el suyo propio si
    assert [v[0] for v in vistos] == ["wifi", "bt", "bt"]


def test_registro_guarda_atomico_y_cuenta_crashes(tmp_path: Path) -> None:
    r = Registro(str(tmp_path), reloj=lambda: 1_000_000.0)
    r.causa("zombi", Medida(True, True, True, True, False, False))
    r.remedio("reasociar")
    r.crash()
    assert r.guardar() and not (tmp_path / "estado.tmp").exists()
    r2 = Registro(str(tmp_path), reloj=lambda: 1_000_000.0)
    assert r2.datos["causas"] == {"zombi": 1} and r2.crashes_desde(60) == 1


def test_registro_corrupto_empieza_de_cero(tmp_path: Path) -> None:
    (tmp_path / "estado.json").write_text("{roto")
    assert Registro(str(tmp_path)).datos["causas"] == {}


def test_config_tolera_archivo_ausente_roto_y_tipos_malos(tmp_path: Path) -> None:
    assert config.cargar(str(tmp_path / "no.toml")) == Config()
    (tmp_path / "roto.toml").write_text("modo = ")
    assert config.cargar(str(tmp_path / "roto.toml")) == Config()
    (tmp_path / "c.toml").write_text('modo = "observar"\nintervalo = 5\nconfirmar = "dos"\nraro = 1\n')
    c = config.cargar(str(tmp_path / "c.toml"))
    assert (c.modo, c.intervalo, c.confirmar) == ("observar", 5.0, 2)
    (tmp_path / "r.toml").write_text('modo = "borrar"\nintervalo = 300\nmax_resets_hora = -1\n')
    assert config.cargar(str(tmp_path / "r.toml")) == Config()  # fuera de rango: valores por defecto


def test_escucha_no_confunde_la_lista_de_modulos_con_un_crash() -> None:
    e = Escucha(lambda *_: None, reloj=lambda: 0.0)
    assert not e.procesar("Modules linked in: rtw88_8821ce rtw88_core btusb btrtl")
    assert e.procesar("WARNING: CPU: 1 at drivers/net/wireless/realtek/rtw88/main.c:640 rtw_fw_recovery+0x2")
    assert e.procesar("rtw_8821ce 0000:02:00.0: failed to send h2c command")


def test_sd_notify_envia_al_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ruta = str(tmp_path / "n.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as srv:
        srv.bind(ruta)
        monkeypatch.setenv("NOTIFY_SOCKET", ruta)
        assert servicio.notificar("WATCHDOG=1")
        assert srv.recv(64) == b"WATCHDOG=1"
    monkeypatch.delenv("NOTIFY_SOCKET")
    assert not servicio.notificar("READY=1")


def test_sistema_real_nunca_lanza_y_respeta_el_tope() -> None:
    s = SistemaReal()
    t0 = time.monotonic()
    assert s.correr(["sleep", "5"], tope=0.3).rc == 124 and time.monotonic() - t0 < 2
    assert s.correr(["no-existe-esta-orden"]).rc == 127
    assert not s.escribir("/sys/no/existe", "1")  # va por proceso hijo con tope
    assert s.leer("/no/existe") is None
    assert os.path.exists("/proc/self")  # entorno sano


def test_cerrojo_un_solo_actor_a_la_vez(tmp_path: Path) -> None:
    ruta = str(tmp_path / "c.lock")
    with cerrojo.exclusivo(False, ruta) as primero, cerrojo.exclusivo(False, ruta) as segundo:
        assert primero and not segundo
    with cerrojo.exclusivo(False, ruta) as despues:
        assert despues  # se libero al salir


def test_cli_sin_argumentos_completos_muestra_la_ayuda(capsys: pytest.CaptureFixture[str]) -> None:
    from radio_rtw88.__main__ import main

    assert main(["probar"]) == 2 and main(["probar", "borrar-todo"]) == 2
    assert "controlador-radio" in capsys.readouterr().err
