"""Escalera de reparacion del Bluetooth Realtek USB: del paso mas suave al mas fuerte, y los pasos USB
profundos (authorized, usbreset) solo si se encendieron a proposito."""

from dataclasses import replace

from falso import SistemaFalso
from radio_rtw88 import bluetooth
from radio_rtw88.config import Config
from radio_rtw88.sistema import Resultado

CFG = Config(bt_reponer=("nap.service",))


def test_responde_exige_un_comando_hci_real() -> None:
    s = SistemaFalso()
    assert bluetooth.responde(s, CFG)
    s.bt_vivo = False
    assert bluetooth.responde(s, CFG) is False
    s.al_correr["hcitool"] = lambda _o: Resultado(127, error="no existe")
    assert bluetooth.responde(s, CFG) is None  # sin la herramienta no se sabe: no es falla del hardware


def test_halla_el_adaptador_usb_por_el_hci_o_por_vendedor_producto() -> None:
    s = SistemaFalso()
    assert bluetooth.dispositivo_usb(s, CFG) == "1-10"
    s.enlaces.clear()  # el hci desaparecio: se busca en USB por 0bda:b00a
    s.archivos |= {
        "/sys/bus/usb/devices/1-10/idVendor": "0bda\n",
        "/sys/bus/usb/devices/1-10/idProduct": "b00a\n",
    }
    assert bluetooth.dispositivo_usb(s, CFG) == "1-10"


def test_religar_desliga_y_liga_cada_interfaz_y_repone_el_nap() -> None:
    s = SistemaFalso()
    s.bt_vivo = False

    def revive() -> bool:
        s.bt_vivo = True
        return True

    s.al_escribir[f"{bluetooth.BTUSB}/bind"] = revive
    ok, paso = bluetooth.reparar(s, CFG)
    assert ok and paso == "religar btusb"
    assert (f"{bluetooth.BTUSB}/unbind", "1-10:1.0") in s.escrituras
    assert (f"{bluetooth.BTUSB}/unbind", "1-10:1.1") in s.escrituras
    assert s.ordeno("systemctl", "start", "--no-block", "nap.service")
    assert not s.ordeno("usbreset") and not any(r.endswith("authorized") for r, _ in s.escrituras)


def test_pasos_usb_profundos_solo_si_estan_encendidos() -> None:
    s = SistemaFalso()
    s.bt_vivo = False
    ok, _ = bluetooth.reparar(s, CFG)
    assert not ok and not s.ordeno("usbreset")
    assert not s.ordeno("systemctl")  # sin reparar no se reponen unidades
    s.al_correr["usbreset"] = lambda _o: (setattr(s, "bt_vivo", True), Resultado(0))[1]
    ok, paso = bluetooth.reparar(s, replace(CFG, bt_usb_profundo=True))
    assert ok and paso == "usbreset"
    assert ("/sys/bus/usb/devices/1-10/authorized", "0") in s.escrituras  # antes probo authorized
