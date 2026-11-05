"""Eleccion de banda (5 GHz primero) y convivencia con el Bluetooth en 2,4 GHz."""

from dataclasses import replace

import pytest

from falso import SistemaFalso
from radio_rtw88 import banda
from radio_rtw88.config import Config
from radio_rtw88.diagnostico import Estado
from radio_rtw88.sistema import Resultado
from radio_rtw88.sondas import Medida

CFG = replace(Config(), conexion_2g="casa-2g")
HCI_AFH_OK = "< HCI Command: ogf 0x03, ocf 0x003f, plen 10\n> HCI Event: 0x0e plen 4\n  02 3F 0C 00\n"


class Casa(SistemaFalso):
    def __init__(self) -> None:
        super().__init__()
        self.senal = {"casa": -60, "casa2": -55}  # dBm de cada SSID en el escaneo
        self.mapas: list[list[str]] = []

    def correr(self, orden: list[str], tope: float = 20) -> Resultado:
        if orden[:2] == ["nmcli", "-g"] and orden[2] == "802-11-wireless.ssid":
            return Resultado(0, ("casa2" if orden[-1] == "casa-2g" else "casa") + "\n")
        if orden[-2:] == ["scan", "dump"]:
            return Resultado(
                0, "".join(f"BSS x\n\tsignal: {v}.00 dBm\n\tSSID: {k}\n" for k, v in self.senal.items())
            )
        if orden[0] == "hcitool" and orden[4:6] == ["0x03", "0x003F"]:
            self.mapas.append(orden[6:])
            return Resultado(0, HCI_AFH_OK)
        return super().correr(orden, tope)


class Reloj:
    t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def caso():
    s, reloj, notas = Casa(), Reloj(), []
    b = banda.Banda(s, CFG, lambda tipo, **d: notas.append(d), reloj)
    return b, s, reloj, notas


def medida(senal: int, frecuencia: int) -> Medida:
    return Medida(True, True, True, True, True, True, senal, 100.0, frecuencia)


def correr(b: banda.Banda, reloj: Reloj, m: Medida, segundos: float) -> None:
    fin = reloj.t + segundos
    while reloj.t <= fin:
        b.vigilar(Estado.SANO, m)
        reloj.t += 5


def test_con_buena_senal_se_queda_en_5_ghz(caso) -> None:
    b, s, reloj, notas = caso
    correr(b, reloj, medida(-60, 5745), 600)
    assert notas == [] and s.activa == "wifi-casa"


def test_lejos_y_con_2_4_ghz_claramente_mejor_baja_tras_un_minuto(caso) -> None:
    b, s, reloj, notas = caso
    s.senal = {"casa": -80, "casa2": -66}
    correr(b, reloj, medida(-80, 5745), banda.SOSTENIDO - 10)
    assert notas == []  # un bajon corto no basta
    correr(b, reloj, medida(-80, 5745), 30)
    assert s.activa == "casa-2g" and notas[-1]["perfil"] == "casa-2g"


def test_si_2_4_ghz_no_gana_lo_suficiente_no_cambia(caso) -> None:
    b, s, reloj, notas = caso
    s.senal = {"casa": -78, "casa2": -75}
    correr(b, reloj, medida(-78, 5745), 300)
    assert notas == []


def test_en_2_4_ghz_vuelve_a_5_ghz_solo_con_senal_buena_y_tras_la_permanencia(caso) -> None:
    b, s, reloj, notas = caso
    b.ultimo_cambio = reloj.t
    s.senal = {"casa": -64, "casa2": -50}
    correr(b, reloj, medida(-50, 2437), banda.PERMANENCIA - 20)
    assert notas == []
    correr(b, reloj, medida(-50, 2437), banda.CADA_BUSQUEDA + 40)
    assert s.activa == "wifi-casa" and notas[-1]["perfil"] == "wifi-casa"


def test_histeresis_no_vuelve_a_5_ghz_con_senal_justa(caso) -> None:
    b, s, reloj, notas = caso
    s.activa = "casa-2g"
    s.senal = {"casa": -70, "casa2": -50}  # sobre el umbral de bajada (-75) pero bajo el de subida (-67)
    correr(b, reloj, medida(-50, 2437), 900)
    assert notas == [] and s.activa == "casa-2g"


def test_sin_perfil_de_2_4_ghz_no_hace_nada() -> None:
    s = Casa()
    b = banda.Banda(s, Config())
    b.vigilar(Estado.SANO, medida(-85, 5745))
    assert s.mapas == []


def test_el_mapa_del_bluetooth_libera_todo_en_5_ghz_y_aparta_el_canal_en_2_4_ghz() -> None:
    assert banda.mapa_afh(5745) == banda.TODOS_LIBRES
    mapa = banda.mapa_afh(2437)  # canal 6: 2426-2448 MHz -> canales Bluetooth 24 a 46 apartados
    bits = [(int(mapa[k // 8], 16) >> (k % 8)) & 1 for k in range(79)]
    assert bits[23] == 1 and bits[24:47] == [0] * 23 and bits[47] == 1


def test_avisa_al_bluetooth_solo_cuando_cambia_el_canal(caso) -> None:
    b, s, _, _ = caso
    for _ in range(3):
        b.convivencia(2437)
    b.convivencia(5745)
    assert len(s.mapas) == 2 and s.mapas[-1] == banda.TODOS_LIBRES
