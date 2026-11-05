"""Eventos de la wifi en vivo (nl80211) y ritmo adaptativo de las revisiones."""

from pathlib import Path

from falso import SistemaFalso
from radio_rtw88 import escucha_red, principal
from radio_rtw88.config import Config

C = Config()


def test_clasifica_las_fallas_y_las_vueltas_de_la_interfaz() -> None:
    i = C.iface
    assert escucha_red.clasificar(f"1.0: {i} (phy #0): disconnected (by AP) reason: 4", i) == "falla"
    assert escucha_red.clasificar(f"1.0: {i} (phy #0): deauth 02:00:00:00:00:01 -> me", i) == "falla"
    assert (
        escucha_red.clasificar(f"{i} (phy #0): connection quality monitor event: beacon loss", i) == "falla"
    )
    msg = f"{i} (phy #0): connection quality monitor event: peer 02:00:00:00:00:01 didn't ACK 50 packets"
    assert escucha_red.clasificar(msg, i) == "falla"
    msg = f"{i} (phy #0): connection quality monitor event: RSSI went below threshold"
    assert escucha_red.clasificar(msg, i) == "falla"
    assert escucha_red.clasificar(f"{i} (phy #0): connected to 02:00:00:00:00:01", i) == "vuelta"


def test_ignora_escaneos_y_otras_interfaces() -> None:
    assert escucha_red.clasificar(f"{C.iface} (phy #0): scan started", C.iface) is None
    assert escucha_red.clasificar("wlan9 (phy #3): disconnected", C.iface) is None


def test_una_falla_despierta_al_bucle_y_acorta_el_ritmo(tmp_path: Path) -> None:
    c = principal.Controlador(SistemaFalso(), Config(estado_dir=str(tmp_path)))
    assert c.intervalo() == C.intervalo_estable  # todo sano: ritmo largo, menos CPU
    c.escucha_red.procesar(f"{C.iface} (phy #0): disconnected (local request)")
    assert c.despertar.is_set() and c.intervalo() == C.intervalo


def test_con_falla_en_curso_revisa_al_ritmo_corto(tmp_path: Path) -> None:
    c = principal.Controlador(SistemaFalso(), Config(estado_dir=str(tmp_path)))
    c.fallas = 1
    assert c.intervalo() == C.intervalo


def test_arma_el_umbral_de_senal_en_el_kernel() -> None:
    s = SistemaFalso()
    assert escucha_red.armar_umbral(s, C)
    assert s.ordeno("iw", "dev", C.iface, "cqm", "rssi", str(C.umbral_senal), str(C.histeresis_senal))
