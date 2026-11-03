from falso import SistemaFalso
from radio_rtw88.config import Config
from radio_rtw88.diagnostico import Estado
from radio_rtw88.respaldo import Respaldo

CFG = Config(bt_celular="bt-celular")


class Reloj:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def armar() -> tuple[SistemaFalso, Reloj, Respaldo, list[dict[str, object]]]:
    s, reloj, eventos = SistemaFalso(), Reloj(), []
    r = Respaldo(s, CFG, lambda tipo, **d: eventos.append({"tipo": tipo, **d}), reloj)
    return s, reloj, r, eventos


def test_red_local_sin_internet_solo_sube_el_bluetooth() -> None:
    # el cluster va por la red local: la wifi no se mueve al celular aunque se vea
    s, reloj, r, eventos = armar()
    s.otras_redes = ["wifi-celular"]
    r.atender(Estado.PROVEEDOR, 1)
    assert not s.bt  # una sola revision no basta (histeresis)
    for _ in range(20):
        reloj.t += 15
        r.atender(Estado.PROVEEDOR, CFG.confirmar)
    assert s.bt and s.activa == "wifi-casa"
    assert eventos[0]["accion"] == "sube bluetooth" and eventos[0]["ok"]


def test_router_ausente_bluetooth_ya_y_wifi_del_celular_despues() -> None:
    s, reloj, r, _ = armar()
    s.otras_redes = ["wifi-celular"]
    r.atender(Estado.AP_AUSENTE, CFG.confirmar)
    assert s.bt and s.activa == "wifi-casa"  # aun no: el router puede estar reiniciandose
    reloj.t += CFG.espera_celular + 1
    r.atender(Estado.AP_AUSENTE, CFG.confirmar + 12)
    assert s.activa == "wifi-celular"


def test_sin_wifi_del_celular_queda_el_bluetooth() -> None:
    s, reloj, r, _ = armar()
    r.atender(Estado.AP_AUSENTE, CFG.confirmar)
    reloj.t += CFG.espera_celular + 1
    r.atender(Estado.AP_AUSENTE, CFG.confirmar + 12)
    assert s.bt and s.activa == "wifi-casa"


def test_bluetooth_que_no_conecta_usa_bluetoothctl_y_espera_para_reintentar() -> None:
    s, reloj, r, eventos = armar()
    s.no_suben = {"bt-celular"}
    r.atender(Estado.PROVEEDOR, CFG.confirmar)
    assert s.ordeno("bluetoothctl", "connect", "00:11:22:33:44:55") and not eventos[0]["ok"]
    antes = len(s.ordenes)
    reloj.t += 15
    r.atender(Estado.PROVEEDOR, CFG.confirmar + 1)
    assert not any(o[:3] == ["nmcli", "connection", "up"] for o in s.ordenes[antes:])


def test_en_el_celular_sin_internet_no_es_el_radio() -> None:
    s, _, r, _ = armar()
    assert r.ajustar(Estado.ZOMBI) is Estado.ZOMBI
    s.activa = "wifi-celular"
    assert r.ajustar(Estado.ZOMBI) is Estado.PROVEEDOR and r.ajustar(Estado.SANO) is Estado.SANO


def test_vuelve_a_la_casa_cuando_la_ve_y_luego_suelta_el_bluetooth() -> None:
    s, reloj, r, _ = armar()
    s.activa, s.bt, s.ssid_visible = "wifi-celular", True, False
    r.atender(Estado.SANO, 0)
    assert s.activa == "wifi-celular"  # la casa no se ve
    s.ssid_visible = True
    reloj.t += CFG.volver_casa - 1
    r.atender(Estado.SANO, 0)
    assert s.activa == "wifi-celular"  # todavia no toca buscarla
    reloj.t += 2
    r.atender(Estado.SANO, 0)
    assert s.activa == "wifi-casa" and s.bt
    reloj.t += CFG.soltar_bt
    r.atender(Estado.SANO, 0)
    assert not s.bt


def test_si_la_casa_no_levanta_regresa_al_celular() -> None:
    s, _, r, _ = armar()
    s.activa, s.no_suben = "wifi-celular", {"wifi-casa"}
    r.atender(Estado.SANO, 0)
    assert s.activa == "wifi-celular" and s.ordeno("nmcli", "connection", "up", "wifi-casa")


def test_modo_observar_no_toca_nada() -> None:
    from dataclasses import replace

    s = SistemaFalso()
    Respaldo(s, replace(CFG, modo="observar")).atender(Estado.AP_AUSENTE, 99)
    assert s.ordenes == []


def test_sin_respaldo_propio_no_elige_red_pero_sigue_ajustando() -> None:
    from dataclasses import replace

    s = SistemaFalso()
    r = Respaldo(s, replace(CFG, respaldo=False))
    r.atender(Estado.AP_AUSENTE, 99)
    assert not any(o[:3] == ["nmcli", "connection", "up"] for o in s.ordenes)
    s.activa = "wifi-celular"
    assert r.ajustar(Estado.ZOMBI) is Estado.PROVEEDOR  # en el celular no se toca el hardware


def test_con_cable_util_no_mueve_la_wifi_ni_sube_el_bluetooth(monkeypatch) -> None:
    # el cable USB del celular es el respaldo: la wifi sigue en la red local y el ruteo hace el resto
    from radio_rtw88 import perfiles

    monkeypatch.setattr(perfiles, "interfaz_anclaje", lambda: "enx0")
    s, reloj, r, _ = armar()
    s.otras_redes = ["wifi-celular"]
    for _ in range(30):
        reloj.t += 15
        r.atender(Estado.AP_AUSENTE, CFG.confirmar + 5)
    assert not s.bt and s.activa == "wifi-casa"
    assert s.ordeno("ping", "-c1", "-W2", "-I", "enx0")


def test_cable_sin_internet_no_cuenta_como_respaldo(monkeypatch) -> None:
    from radio_rtw88 import perfiles

    monkeypatch.setattr(perfiles, "interfaz_anclaje", lambda: "enx0")
    s, _, r, _ = armar()
    s.internet = False  # el falso responde igual por cualquier interfaz
    r.atender(Estado.PROVEEDOR, CFG.confirmar)
    assert s.bt
