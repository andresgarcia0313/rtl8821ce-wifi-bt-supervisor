"""Cada funcion que habla con el sistema tiene su try/except con una alternativa util para su proposito."""

import ast
from pathlib import Path

import pytest

from falso import SistemaFalso
from radio_rtw88 import acciones, bluetooth, sondas
from radio_rtw88.config import Config
from radio_rtw88.intentos import resiste
from radio_rtw88.sistema import Resultado

C = Config()
PAQUETE = Path(__file__).parent.parent / "src" / "radio_rtw88"
CON_SISTEMA = ("sondas", "bluetooth", "acciones", "red", "perfiles", "escenario")


def _publicas(arbol: ast.Module) -> list[ast.FunctionDef]:
    funciones = [n for n in arbol.body if isinstance(n, ast.FunctionDef)]
    for clase in (n for n in arbol.body if isinstance(n, ast.ClassDef)):
        funciones += [n for n in clase.body if isinstance(n, ast.FunctionDef)]
    return [f for f in funciones if not f.name.startswith("_")]


def _protegida(f: ast.FunctionDef) -> bool:
    return any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "resiste"
        for d in f.decorator_list
    )


@pytest.mark.parametrize("modulo", CON_SISTEMA)
def test_ninguna_funcion_publica_queda_sin_su_alternativa(modulo: str) -> None:
    arbol = ast.parse((PAQUETE / f"{modulo}.py").read_text())
    sin = [f.name for f in _publicas(arbol) if not _protegida(f) and f.name != "router_responde"]
    assert sin == [], f"{modulo}: funciones sin @resiste {sin}"


def _lanza(_orden: list[str]) -> Resultado:
    raise RuntimeError("salida inesperada")


def test_sonda_del_chip_que_lanza_da_el_chip_por_vivo(monkeypatch: pytest.MonkeyPatch) -> None:
    s = SistemaFalso()
    monkeypatch.setattr(s, "leer", lambda _r: 1 // 0)
    assert sondas.chip_vivo(s, C) is True  # nunca reiniciar la tarjeta por una lectura rota


def test_enlace_que_lanza_usa_el_estado_de_la_interfaz() -> None:
    s = SistemaFalso()
    s.al_correr["iw"] = _lanza
    assert sondas.enlace(s, C) == (True, None, None, None)  # operstate "up"
    s.archivos[f"/sys/class/net/{C.iface}/operstate"] = "dormant"
    assert sondas.enlace(s, C)[0] is False


def test_medida_que_lanza_cae_a_la_medida_minima(monkeypatch: pytest.MonkeyPatch) -> None:
    s = SistemaFalso()
    monkeypatch.setattr(sondas, "chip_vivo", lambda *_a: 1 // 0)
    m = sondas.medir(s, C)
    assert m.interfaz and m.firmware and m.asociado and m.internet


def test_bluetooth_que_lanza_es_no_se_sabe_y_nunca_falla() -> None:
    s = SistemaFalso()
    s.al_correr["hcitool"] = _lanza
    assert bluetooth.responde(s, C) is None


def test_remedio_que_lanza_cuenta_como_no_logrado() -> None:
    s = SistemaFalso()
    s.al_correr["nmcli"] = _lanza
    assert acciones.reasociar(s, C) is False


def test_si_la_alternativa_tambien_lanza_el_error_sube() -> None:
    @resiste(lambda: 1 // 0)
    def rota() -> int:
        raise ValueError

    with pytest.raises(ZeroDivisionError):
        rota()


def test_router_que_ignora_el_ping_pero_contesta_arp_no_es_zombi() -> None:
    s = SistemaFalso()
    s.internet = False
    s.al_correr["ping"] = lambda _o: Resultado(1)
    assert sondas.router_responde(s, C)  # arping del falso contesta por la puerta
    assert sondas.medir(s, C).puerta
