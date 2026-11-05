"""Canal congestionado: distancia, congestion o canal limpio, y RTS/CTS solo mientras haga falta."""

from falso import SistemaFalso
from radio_rtw88 import canal
from radio_rtw88.config import Config
from radio_rtw88.sistema import Resultado
from radio_rtw88.sondas import Medida

C = Config()


def ping_resumen(perdida: int, media: float, maxima: float) -> Resultado:
    texto = f"5 packets transmitted, 5 received, {perdida}% packet loss, time 800ms\n"
    return Resultado(0, texto + f"rtt min/avg/max/mdev = 3.0/{media}/{maxima}/1.0 ms\n")


class Reloj:
    t = 1000.0

    def __call__(self) -> float:
        return self.t


def medida(senal: int) -> Medida:
    return Medida(True, True, True, True, True, True, senal, 300.0, 5745)


def nuevo() -> tuple[canal.Canal, SistemaFalso, Reloj, list[dict[str, object]], dict[str, Resultado]]:
    s, reloj, notas, aire = SistemaFalso(), Reloj(), [], {"ping": ping_resumen(0, 4.0, 8.0)}
    s.archivos[f"/sys/class/net/{C.iface}/phy80211/name"] = "phy0\n"
    s.al_correr["ping"] = lambda _o: aire["ping"]
    return canal.Canal(s, C, lambda tipo, **d: notas.append(d), reloj), s, reloj, notas, aire


def test_clasifica_distancia_congestion_y_limpio() -> None:
    assert canal.clasificar(-80, (20.0, 40.0, 300.0)) == "lejos"
    assert canal.clasificar(-50, (0.0, 4.0, 120.0)) == "congestionado"
    assert canal.clasificar(-50, (20.0, 4.0, 9.0)) == "congestionado"
    assert canal.clasificar(-50, (40.0, 5.0, 7.0), arp_ok=True) == "limpio"  # el router ignora pings
    assert canal.clasificar(-50, (0.0, 4.0, 9.0)) == "limpio"


def test_congestion_enciende_rts_y_diez_minutos_limpios_lo_apagan() -> None:
    c, s, reloj, notas, aire = nuevo()
    aire["ping"] = ping_resumen(20, 30.0, 150.0)
    c.vigilar(medida(-50))
    assert c.rts and s.ordeno("iw", "phy", "phy0", "set", "rts", str(canal.UMBRAL_RTS))
    aire["ping"] = ping_resumen(0, 4.0, 8.0)
    for _ in range(9):
        reloj.t += canal.CADA
        c.vigilar(medida(-50))
    assert c.rts  # aun no pasan 10 min limpios
    reloj.t += canal.CADA * 2
    c.vigilar(medida(-50))
    assert not c.rts and s.ordeno("iw", "phy", "phy0", "set", "rts", "off")
    assert notas[0]["estado"] == "congestionado"


def test_lejos_no_enciende_rts_lo_atiende_la_banda() -> None:
    c, _, _, notas, aire = nuevo()
    aire["ping"] = ping_resumen(40, 60.0, 400.0)
    c.vigilar(medida(-82))
    assert not c.rts and notas[0]["estado"] == "lejos"


def test_mide_una_vez_por_minuto() -> None:
    c, s, reloj, _, _ = nuevo()
    c.vigilar(medida(-50))
    reloj.t += 10
    c.vigilar(medida(-50))
    assert sum(o[0] == "ping" for o in s.ordenes) == 1


def test_router_que_ignora_pings_pero_contesta_arp_no_enciende_rts() -> None:
    c, s, _, notas, aire = nuevo()
    aire["ping"] = ping_resumen(40, 5.0, 7.0)
    s.al_correr["arping"] = lambda _o: Resultado(0)
    c.vigilar(medida(-47))
    assert not c.rts and notas == []
