from pathlib import Path

import pytest

from falso import SistemaFalso
from radio_rtw88 import demonio, principal, servicio
from radio_rtw88.config import Config
from radio_rtw88.diagnostico import Estado


@pytest.fixture
def avisos(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    enviados: list[tuple[str, str]] = []
    monkeypatch.setattr(servicio, "avisar", lambda n, t: enviados.append((n, t)))
    monkeypatch.setattr(servicio, "notificar", lambda _m: True)
    return enviados


def nuevo(tmp_path: Path, s: SistemaFalso) -> principal.Controlador:
    return principal.Controlador(s, Config(estado_dir=str(tmp_path)))


def test_confirma_antes_de_actuar_y_avisa_al_recuperar(tmp_path: Path, avisos: list) -> None:
    s = SistemaFalso()
    s.puerta = s.internet = False
    c = nuevo(tmp_path, s)
    assert c.vuelta() is Estado.ZOMBI and not s.ordeno("nmcli", "device", "disconnect")
    s.al_correr["nmcli"] = lambda o: _revivir(s, o)
    assert c.vuelta() is Estado.ZOMBI and s.ordeno("nmcli", "device", "disconnect")
    assert c.fallas == 0 and avisos[-1][0] == "recovered"
    assert c.registro.datos["remedios"] == {"reasociar": 1}


def _revivir(s: SistemaFalso, orden: list[str]):  # type: ignore[no-untyped-def]
    from radio_rtw88.sistema import Resultado

    if orden[:3] == ["nmcli", "connection", "up"]:
        s.puerta = s.internet = True
    if orden[:2] == ["nmcli", "-t"]:
        return Resultado(0, "wifi-casa\n")
    return Resultado(0, "wifi-casa\n" if orden[:2] == ["nmcli", "-g"] else "")


def test_crash_en_vivo_actua_sin_esperar_confirmacion(tmp_path: Path, avisos: list) -> None:
    s = SistemaFalso()
    s.puerta = s.internet = False
    c = nuevo(tmp_path, s)
    c.al_kernel("wifi", "rtw_8821ce 0000:02:00.0: firmware crash, start reset and recover")
    assert c.vuelta() is Estado.FIRMWARE
    assert any(r.endswith("fw_crash") for r, _ in s.escrituras)
    assert c.registro.crashes_desde(60) == 1 and avisos[-1][0] == "critical"


def test_proveedor_caido_no_avisa_critico_ni_toca_hardware(tmp_path: Path, avisos: list) -> None:
    s = SistemaFalso()
    s.internet = False
    c = nuevo(tmp_path, s)
    for _ in range(3):
        assert c.vuelta() is Estado.PROVEEDOR
    assert avisos == [] and s.escrituras == []  # ni una escritura en /sys


def test_una_vuelta_que_lanza_aplica_el_respaldo_minimo(
    tmp_path: Path, avisos: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = SistemaFalso()
    c = nuevo(tmp_path, s)
    monkeypatch.setattr(c, "vuelta", lambda: 1 // 0)
    monkeypatch.setattr(c.escucha, "iniciar", lambda: None)
    monkeypatch.setattr(demonio, "MAX_ERRORES", 2)
    monkeypatch.setattr(c.despertar, "wait", lambda _t: True)
    assert demonio.bucle(c) == 1  # tras MAX_ERRORES sale para que systemd decida
    assert s.ordeno("ping")  # el respaldo comprobo la wifi


def test_bluetooth_mudo_se_confirma_y_se_repara_con_el_paso_mas_suave(tmp_path: Path, avisos: list) -> None:
    s = SistemaFalso()
    c = nuevo(tmp_path, s)
    s.bt_vivo = False
    c.vigia_bt.ultimo = -1e9  # pasada la gracia del arranque
    c.vigilar_bt()  # primera lectura mala: solo sospecha
    assert not s.ordeno("bluetoothctl", "power", "on")
    c.vigia_bt.ultimo = -1e9
    s.al_correr["bluetoothctl"] = lambda o: _bt_enciende(s, o)
    c.vigilar_bt()  # confirmada: repara
    assert s.ordeno("bluetoothctl", "power", "on") and not s.ordeno(
        "rfkill", "block"
    )  # la evidencia corre rfkill a secas
    assert [e["tipo"] for e in c.episodios.bitacora.ultimos()] == ["falla", "remedio"]


def _bt_enciende(s: SistemaFalso, orden: list[str]):  # type: ignore[no-untyped-def]
    from radio_rtw88.sistema import Resultado

    if orden[1:3] == ["power", "on"]:
        s.bt_vivo = True
    return Resultado(0, "\tPowered: yes\n" if s.bt_vivo else "")


def test_cada_episodio_deja_bitacora_y_evidencia(tmp_path: Path, avisos: list) -> None:
    s = SistemaFalso()
    s.puerta = s.internet = False
    c = nuevo(tmp_path, s)
    c.vuelta()  # falla nueva: evidencia antes de actuar
    s.puerta = s.internet = True
    c.vuelta()  # se arreglo sola
    eventos = c.episodios.bitacora.ultimos()
    assert [e["tipo"] for e in eventos] == ["falla", "recuperada_sola"]
    falla = eventos[0]
    assert falla["causa"] == "zombi" and falla["medida"]["frecuencia"] == 5745
    assert {"carga", "memoria_libre_mb", "bssid", "cable_usb", "salida_internet"} <= set(falla["escenario"])
    assert falla["escenario"]["balizas_perdidas"] == 34 and falla["escenario"]["senal_media"] == -36
    carpeta = Path(falla["evidencia"])
    assert {"kernel.txt", "wifi.txt", "pci.txt", "bluetooth.txt"} <= {f.name for f in carpeta.iterdir()}
    assert eventos[1]["evidencia_falla"] == falla["evidencia"]


def test_error_del_bluetooth_en_el_kernel_queda_anotado(tmp_path: Path, avisos: list) -> None:
    c = nuevo(tmp_path, SistemaFalso())
    c.al_kernel("bt", "Bluetooth: hci0: Hardware error 0x0b")
    c.vuelta()
    e = c.episodios.bitacora.ultimos()[-1]
    assert (e["equipo"], e["tipo"]) == ("bt", "error_kernel") and "Hardware error" in e["detalle"]
    assert c.registro.crashes_desde(60) == 0  # un error del Bluetooth no cuenta como crash de la wifi


def test_lineas_repetidas_del_kernel_dan_una_sola_evidencia(tmp_path: Path, avisos: list) -> None:
    c = nuevo(tmp_path, SistemaFalso())
    for _ in range(5):
        c.al_kernel("bt", "Bluetooth: hci0: command 0x0c03 tx timeout")
    c.vuelta()
    eventos = [e for e in c.episodios.bitacora.ultimos() if e["tipo"] == "error_kernel"]
    assert len(eventos) == 5 and sum(1 for e in eventos if e["evidencia"]) == 1


def test_con_la_cpu_muy_presionada_confirma_mas_antes_de_actuar(tmp_path: Path) -> None:
    s = SistemaFalso()
    c = nuevo(tmp_path, s)
    s.archivos["/proc/pressure/cpu"] = "some avg10=12.00 avg60=10.00 avg300=9.00 total=1\n"
    assert c.confirmar() == c.cfg.confirmar
    s.archivos["/proc/pressure/cpu"] = "some avg10=75.00 avg60=40.00 avg300=20.00 total=1\n"
    assert c.confirmar() == c.cfg.confirmar + 2
