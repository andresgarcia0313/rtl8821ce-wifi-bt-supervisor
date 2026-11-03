"""Vigia del cable: si Android apaga el anclaje tras reiniciarse el puerto USB, avisa una sola vez."""

import pytest

from falso import SistemaFalso
from radio_rtw88 import vigia_cable
from radio_rtw88.sistema import Resultado


class Reloj:
    t = 0.0

    def __call__(self) -> float:
        return self.t


def armar(monkeypatch: pytest.MonkeyPatch, iface: str | None, con_ip: bool):
    s, reloj, avisos, eventos = SistemaFalso(), Reloj(), [], []
    salida = f"5: {iface}    inet 10.0.0.2/24 brd ...\n" if con_ip else ""
    s.al_correr["ip"] = lambda _o: Resultado(0, salida)
    monkeypatch.setattr(vigia_cable.servicio, "avisar", lambda nivel, _t: avisos.append(nivel))
    v = vigia_cable.VigiaCable(s, lambda tipo, **d: eventos.append(d), reloj, lambda: iface)
    return s, v, reloj, avisos, eventos


def test_sin_cable_no_hay_nada_que_vigilar(monkeypatch: pytest.MonkeyPatch) -> None:
    s, v, reloj, avisos, _ = armar(monkeypatch, None, False)
    for _ in range(100):
        reloj.t += 60
        v.vigilar()
    assert avisos == [] and not s.ordenes


def test_cable_sin_direccion_avisa_una_vez_tras_la_gracia_y_avisa_al_volver(monkeypatch) -> None:
    s, v, reloj, avisos, eventos = armar(monkeypatch, "enx0", False)
    v.vigilar()
    reloj.t += vigia_cable.GRACIA - 1
    v.vigilar()
    assert avisos == []  # DHCP del celular puede tardar
    for _ in range(50):
        reloj.t += 60
        v.vigilar()
    assert avisos == ["critical"] and eventos[0]["accion"] == "anclaje apagado"
    s.al_correr["ip"] = lambda _o: Resultado(0, "5: enx0    inet 10.0.0.2/24\n")
    v.vigilar()
    assert avisos == ["critical", "recovered"]


def test_cable_con_direccion_no_avisa(monkeypatch: pytest.MonkeyPatch) -> None:
    _, v, reloj, avisos, _ = armar(monkeypatch, "enx0", True)
    for _ in range(50):
        reloj.t += 60
        v.vigilar()
    assert avisos == []
