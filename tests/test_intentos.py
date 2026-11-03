from radio_rtw88 import intentos
from radio_rtw88.intentos import con_respaldo, seguro


def falla() -> bool:
    raise RuntimeError("se cayo")


def test_el_respaldo_hace_la_tarea_cuando_el_primero_lanza() -> None:
    d = con_respaldo("t", [("a", falla), ("b", lambda: False), ("c", lambda: True), ("d", falla)])
    assert d.ok and d.paso == "c" and d.fallidos == ("a", "b")


def test_si_todos_fallan_no_propaga_y_lo_dice() -> None:
    d = con_respaldo("t", [("a", falla), ("b", lambda: False)])
    assert not d.ok and d.paso is None and d.fallidos == ("a", "b")


def test_cada_paso_late_para_el_watchdog() -> None:
    latidos: list[int] = []
    intentos.latido = lambda: latidos.append(1)
    try:
        con_respaldo("t", [("a", lambda: False), ("b", lambda: True)])
    finally:
        intentos.latido = intentos._sin_latido
    assert len(latidos) == 2


def test_seguro_usa_la_alternativa() -> None:
    assert seguro("t", lambda: 1 // 0, lambda: 7) == 7
