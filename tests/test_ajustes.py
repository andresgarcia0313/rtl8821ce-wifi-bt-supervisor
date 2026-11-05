"""Ajustes del driver vigilados: ahorro de energia de la wifi y suspension USB del Bluetooth."""

from dataclasses import replace

from falso import SistemaFalso
from radio_rtw88 import ajustes
from radio_rtw88.config import Config
from radio_rtw88.sistema import Resultado

ENERGIA = "/sys/bus/usb/devices/1-10/power/control"


class Equipo(SistemaFalso):
    def __init__(self) -> None:
        super().__init__()
        self.ahorro = "on"
        self.archivos[ENERGIA] = "auto\n"

    def correr(self, orden: list[str], tope: float = 20) -> Resultado:
        if orden[-2:] == ["get", "power_save"]:
            return Resultado(0, f"Power save: {self.ahorro}\n")
        if orden[-3:] == ["set", "power_save", "off"]:
            self.ahorro = "off"
            return Resultado(0)
        if orden == ["iw", "reg", "get"]:
            return Resultado(0, "global\ncountry CO: DFS-FCC\n")
        return super().correr(orden, tope)

    def escribir(self, ruta: str, texto: str) -> bool:
        self.archivos[ruta] = texto
        return super().escribir(ruta, texto)


def vigia(modo: str = "actuar") -> tuple[ajustes.Ajustes, Equipo, list[dict[str, object]]]:
    s, notas = Equipo(), []
    a = ajustes.Ajustes(s, replace(Config(), modo=modo), lambda tipo, **d: notas.append(d))
    return a, s, notas


def test_corrige_la_suspension_del_bluetooth_y_deja_el_ahorro_a_energia() -> None:
    a, s, notas = vigia()
    assert a.vigilar() == ["bluetooth_suspension_usb"]
    assert s.archivos[ENERGIA] == "on" and s.ahorro == "on"  # el ahorro lo decide el perfil de energia
    assert all(n["corregido"] for n in notas)


def test_en_modo_observar_solo_anota() -> None:
    a, s, notas = vigia("observar")
    a.vigilar()
    assert s.archivos[ENERGIA] == "auto\n"
    assert [n["corregido"] for n in notas] == [False]


def test_revisa_cada_cinco_minutos_no_en_cada_vuelta() -> None:
    a, s, _ = vigia()
    a.vigilar()
    s.archivos[ENERGIA] = "auto\n"
    assert a.vigilar() == []


def test_todo_en_orden_no_toca_nada() -> None:
    a, s, notas = vigia()
    s.ahorro, s.archivos[ENERGIA] = "off", "on\n"
    assert a.vigilar() == [] and notas == [] and s.escrituras == []


def test_lista_las_opciones_al_estilo_windows() -> None:
    s = Equipo()
    s.archivos["/sys/module/rtw88_pci/parameters/disable_aspm"] = "Y\n"
    datos = ajustes.leer_todos(s, Config())
    assert datos == {
        "ahorro_energia_wifi": "on",
        "bluetooth_suspension_usb": "auto",
        "pais_radio": "CO",
        "disable_aspm": "Y",
    }
