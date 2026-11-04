"""Itinerancia minima: fija el unico punto de acceso con la wifi sana y el cable util; lo suelta si falta."""

from dataclasses import replace

import pytest

from falso import SistemaFalso
from radio_rtw88 import itinerancia
from radio_rtw88.config import Config
from radio_rtw88.diagnostico import Estado
from radio_rtw88.sistema import Resultado

CASA, OTRO = "02:00:00:00:00:01", "02:00:00:00:00:09"


def escapado(bssid: str) -> str:
    return bssid.replace(":", "\\:")


class Red(SistemaFalso):
    def __init__(self) -> None:
        super().__init__()
        self.fijado = ""
        self.puntos = [CASA]  # BSSID que anuncian el SSID de la casa

    def correr(self, orden: list[str], tope: float = 20) -> Resultado:
        if orden[:2] == ["nmcli", "-g"] and orden[2] == "802-11-wireless.bssid":
            return Resultado(0, escapado(self.fijado) + "\n")
        if orden[:2] == ["nmcli", "-g"] and orden[2] == "802-11-wireless.ssid":
            return Resultado(0, "casa\n")
        if orden[:4] == ["nmcli", "-t", "-f", "BSSID,SSID"]:
            return Resultado(
                0, "".join(f"{escapado(b)}:casa\n" for b in self.puntos) + f"{escapado(OTRO)}:vecino\n"
            )
        if orden[:3] == ["nmcli", "connection", "modify"]:
            self.fijado = orden[-1]
            return Resultado(0)
        return super().correr(orden, tope)


class Reloj:
    t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def caso(monkeypatch: pytest.MonkeyPatch):
    s, reloj, notas = Red(), Reloj(), []
    cable = {"util": True}
    it = itinerancia.Itinerancia(
        s, replace(Config(), fijar_bssid=True), lambda t, **d: notas.append(d), reloj
    )
    monkeypatch.setattr(it.p, "cable_util", lambda: cable["util"])
    return it, s, reloj, notas, cable


def sano(it: itinerancia.Itinerancia, reloj: Reloj, segundos: float) -> None:
    fin = reloj.t + segundos
    while reloj.t <= fin:
        it.vigilar(Estado.SANO)
        reloj.t += 15


def test_fija_el_unico_punto_de_acceso_tras_diez_minutos_sanos(caso) -> None:
    it, s, reloj, notas, _ = caso
    sano(it, reloj, itinerancia.SANO_ANTES - 30)
    assert s.fijado == ""
    sano(it, reloj, 60)
    assert s.fijado == CASA and notas[-1] == {"accion": "fijar", "bssid": CASA, "ok": True}


def test_sin_cable_de_respaldo_no_reconecta_para_fijar(caso) -> None:
    it, s, reloj, _, cable = caso
    cable["util"] = False
    sano(it, reloj, itinerancia.SANO_ANTES + 60)
    assert s.fijado == ""


def test_con_varios_puntos_de_acceso_deja_la_itinerancia(caso) -> None:
    it, s, reloj, _, _ = caso
    s.puntos = [CASA, "02:00:00:00:00:02"]
    sano(it, reloj, itinerancia.SANO_ANTES + 60)
    assert s.fijado == ""


def test_si_no_vuelve_con_el_punto_fijado_lo_deja_como_estaba(caso, monkeypatch: pytest.MonkeyPatch) -> None:
    it, s, reloj, notas, _ = caso
    monkeypatch.setattr(itinerancia, "red_ok", lambda *_a: False)
    sano(it, reloj, itinerancia.SANO_ANTES + 60)
    assert s.fijado == "" and notas[-1]["ok"] is False


def test_router_nuevo_suelta_la_fijacion(caso) -> None:
    it, s, _, notas, _ = caso
    s.fijado, s.puntos = CASA, ["02:00:00:00:00:03"]
    it.vigilar(Estado.DESASOCIADO)
    assert s.fijado == "" and notas[-1]["accion"] == "soltar"


def test_un_corte_con_el_punto_fijado_visible_no_lo_suelta(caso) -> None:
    it, s, _, _, _ = caso
    s.fijado = CASA
    it.vigilar(Estado.AP_AUSENTE)
    assert s.fijado == CASA


def test_apagado_por_defecto_no_toca_nada() -> None:
    s = Red()
    it = itinerancia.Itinerancia(s, Config())
    it.vigilar(Estado.SANO)
    it.vigilar(Estado.DESASOCIADO)
    assert not s.ordeno("nmcli", "connection", "modify")
