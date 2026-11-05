"""Vigia del Bluetooth: confirma antes de actuar (repararlo corta el canal de rescate), espacia los reintentos
de un controlador que no vuelve y avisa una sola vez por episodio, aun tras reiniciar el demonio."""

from dataclasses import replace

import pytest

from falso import SistemaFalso
from radio_rtw88 import vigia_bt
from radio_rtw88.config import Config


class Reloj:
    t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def vigia(monkeypatch: pytest.MonkeyPatch, tmp_path):
    reloj, avisos, estado = Reloj(), [], {"responde": False, "repara": False, "intentos": 0}

    def reparar(_s: object, _c: object) -> tuple[bool, str | None]:
        estado["intentos"] += 1
        if estado["repara"]:
            estado["responde"] = True
        return estado["repara"], "encender" if estado["repara"] else None

    monkeypatch.setattr(vigia_bt.time, "monotonic", reloj)
    monkeypatch.setattr(vigia_bt.bluetooth, "responde", lambda _s, _c: estado["responde"])
    monkeypatch.setattr(vigia_bt.bluetooth, "reparar", reparar)
    monkeypatch.setattr(vigia_bt.servicio, "avisar", lambda nivel, texto: avisos.append(nivel))
    episodios = type("Ep", (), {"bt": lambda self, *a: None})()
    cfg = replace(Config(), modo="actuar", estado_dir=str(tmp_path))
    v = vigia_bt.VigiaBt(SistemaFalso(), cfg, episodios)  # type: ignore[arg-type]
    reloj.t = vigia_bt.CADA_BT  # pasada la gracia del arranque
    return v, reloj, avisos, estado


def correr_horas(v: vigia_bt.VigiaBt, reloj: Reloj, horas: float) -> None:
    fin = reloj.t + horas * 3600
    while reloj.t < fin:
        v.vigilar()
        reloj.t += 15


def test_una_lectura_mala_no_basta_para_reparar(vigia) -> None:
    v, reloj, _, estado = vigia
    v.vigilar()
    assert estado["intentos"] == 0 and v.sospecha
    estado["responde"] = True
    reloj.t += vigia_bt.CONFIRMAR_BT
    v.vigilar()
    assert estado["intentos"] == 0 and not v.sospecha  # fue una lectura suelta


def test_controlador_trabado_avisa_una_vez_y_espacia_los_intentos(vigia) -> None:
    v, reloj, avisos, estado = vigia
    correr_horas(v, reloj, 24)
    assert avisos == ["critical"]
    assert estado["intentos"] <= 9  # 5, 10, 20... min hasta el tope de 12 h


def test_cuando_vuelve_avisa_recuperado_y_retoma_el_ritmo_normal(vigia) -> None:
    v, reloj, avisos, estado = vigia
    correr_horas(v, reloj, 3)
    estado["responde"] = True
    correr_horas(v, reloj, 13)
    assert avisos == ["critical", "recovered"] and v.fallos == 0


def test_si_el_remedio_lo_repara_no_hay_aviso_critico(vigia) -> None:
    v, reloj, avisos, estado = vigia
    estado["repara"] = True
    correr_horas(v, reloj, 2)
    assert "critical" not in avisos and estado["intentos"] == 1


def test_el_reinicio_del_demonio_no_repite_el_aviso_critico(vigia) -> None:
    v, reloj, avisos, _ = vigia
    correr_horas(v, reloj, 1)
    otro = vigia_bt.VigiaBt(v.s, v.cfg, v.episodios)
    correr_horas(otro, reloj, 1)
    assert avisos == ["critical"] and otro.fallos >= 1


def test_modo_observar_anota_sin_reparar(vigia) -> None:
    v, reloj, _, estado = vigia
    v.cfg = replace(v.cfg, modo="observar")
    correr_horas(v, reloj, 1)
    assert estado["intentos"] == 0


def test_tras_arrancar_espera_antes_de_la_primera_revision(vigia) -> None:
    v, _, _, estado = vigia
    otro = vigia_bt.VigiaBt(v.s, v.cfg, v.episodios)
    otro.vigilar()
    assert not otro.sospecha and estado["intentos"] == 0  # el hci puede no estar listo aun


def test_un_aviso_del_kernel_no_salta_la_espera_tras_remedios_fallidos(vigia) -> None:
    v, reloj, _, estado = vigia
    correr_horas(v, reloj, 0.2)  # primer remedio fallido
    antes = estado["intentos"]
    for _ in range(40):  # un kernel que repite errores cada 15 s durante 10 min
        v.revisar_ya()
        v.vigilar()
        reloj.t += 15
    assert estado["intentos"] == antes  # la espera creciente manda, no el kernel


def test_sin_herramientas_no_se_repara_a_ciegas(vigia, monkeypatch: pytest.MonkeyPatch) -> None:
    v, reloj, _, estado = vigia
    monkeypatch.setattr(vigia_bt.bluetooth, "responde", lambda _s, _c: None)
    correr_horas(v, reloj, 2)
    assert estado["intentos"] == 0


def test_tras_reiniciar_con_fallos_guardados_revisa_a_los_cinco_minutos(vigia) -> None:
    v, reloj, _, _ = vigia
    v._anotar(5)  # espera creciente de horas guardada en disco
    otro = vigia_bt.VigiaBt(v.s, v.cfg, v.episodios)
    reloj.t += vigia_bt.CADA_BT - 1
    otro.vigilar()
    assert not otro.sospecha
    reloj.t += 1
    otro.vigilar()
    assert otro.sospecha  # reviso: el Bluetooth sigue mudo


def test_anota_solo_cuando_un_enlace_se_debilita_o_se_recupera(
    vigia, monkeypatch: pytest.MonkeyPatch
) -> None:
    v, reloj, _, estado = vigia
    estado["responde"] = True
    notas: list[str] = []
    v.episodios = type("Ep", (), {"bt": lambda self, tipo, detalle, *a: notas.append(detalle)})()
    senal = {"02:00:00:00:00:01": -10}
    monkeypatch.setattr(vigia_bt.bluetooth, "senal_enlaces", lambda _s, _c: dict(senal))
    for db in (-10, -45, -50, -5):
        senal["02:00:00:00:00:01"] = db
        reloj.t += vigia_bt.CADA_BT
        v.vigilar()
    assert len(notas) == 2 and "debil" in notas[0] and "recuperado" in notas[1]
