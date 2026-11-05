"""Radio apagada a proposito (rfkill) y regreso de una suspension."""

from pathlib import Path

from falso import SistemaFalso
from radio_rtw88 import principal, sondas
from radio_rtw88.config import Config
from radio_rtw88.diagnostico import SIN_TOCAR_HARDWARE, Estado, diagnosticar


def con_rfkill(tipo: str, soft: str) -> SistemaFalso:
    s = SistemaFalso()
    s.carpetas["/sys/class/rfkill"] = ["rfkill0"]
    s.archivos |= {"/sys/class/rfkill/rfkill0/type": f"{tipo}\n", "/sys/class/rfkill/rfkill0/soft": soft}
    s.archivos["/sys/class/rfkill/rfkill0/hard"] = "0\n"
    return s


def test_wifi_apagada_a_proposito_no_se_repara(tmp_path: Path) -> None:
    s = con_rfkill("wlan", "1\n")
    m = sondas.medir(s, Config())
    assert m.apagada and diagnosticar(m) is Estado.APAGADA and Estado.APAGADA in SIN_TOCAR_HARDWARE
    c = principal.Controlador(s, Config(estado_dir=str(tmp_path), confirmar=1))
    assert c.vuelta() is Estado.APAGADA
    assert not s.ordeno("nmcli", "device", "disconnect") and not s.ordeno("modprobe")


def test_wifi_encendida_se_mide_normal() -> None:
    assert not sondas.medir(con_rfkill("wlan", "0\n"), Config()).apagada


def test_bluetooth_apagado_a_proposito_no_se_repara(tmp_path: Path) -> None:
    s = con_rfkill("bluetooth", "1\n")
    s.bt_vivo = False
    c = principal.Controlador(s, Config(estado_dir=str(tmp_path)))
    c.vigia_bt.ultimo = -1e9
    c.vigia_bt.vigilar()
    assert not c.vigia_bt.sospecha and not s.ordeno("hcitool")


def test_al_despertar_revisa_de_inmediato(tmp_path: Path) -> None:
    c = principal.Controlador(SistemaFalso(), Config(estado_dir=str(tmp_path)))
    c.al_despertar()
    assert c.despertar.is_set() and c.intervalo() == c.cfg.intervalo


def test_un_bloqueo_propio_que_quedo_por_una_reparacion_interrumpida_se_quita(tmp_path: Path) -> None:
    from radio_rtw88 import bluetooth

    s = con_rfkill("bluetooth", "1\n")
    c = principal.Controlador(s, Config(estado_dir=str(tmp_path)))
    s.archivos[bluetooth.marca_rfkill(c.cfg)] = "1"
    c.vigia_bt.ultimo = -1e9
    c.vigia_bt.vigilar()
    assert s.ordeno("rfkill", "unblock", "bluetooth") and s.ordeno("hcitool")


def test_tras_recargar_el_driver_vuelve_a_armar_sus_ajustes(tmp_path: Path) -> None:
    s = SistemaFalso()
    c = principal.Controlador(s, Config(estado_dir=str(tmp_path)))
    c.vuelta()
    c.canal.rts = True
    s.archivos[f"/sys/class/net/{c.cfg.iface}/phy80211/name"] = "phy1\n"
    c.vuelta()
    assert not c.canal.rts and s.ordeno("iw", "dev", c.cfg.iface, "cqm", "rssi")


def test_la_senal_de_despertar_llega_al_controlador_sin_tocar_candados() -> None:
    import os
    import signal
    import threading

    from radio_rtw88 import demonio

    llamado = threading.Event()
    falso = type("C", (), {"al_despertar": lambda self: llamado.set()})()
    try:
        demonio.escuchar_despertar(falso)  # type: ignore[arg-type]
        os.kill(os.getpid(), signal.SIGUSR1)
        assert llamado.wait(2)
    finally:
        signal.set_wakeup_fd(-1)
        signal.signal(signal.SIGUSR1, signal.SIG_DFL)
