from dataclasses import replace

from falso import DEBUGFS, SistemaFalso
from radio_rtw88 import acciones
from radio_rtw88.config import Config
from radio_rtw88.diagnostico import Estado
from radio_rtw88.politica import Politica
from radio_rtw88.sistema import Resultado

CFG = Config()


class Reloj:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_proveedor_y_sano_no_tocan_nada() -> None:
    s = SistemaFalso()
    p = Politica(s, CFG)
    assert p.actuar(Estado.PROVEEDOR) is None and p.actuar(Estado.SANO) is None
    assert s.ordenes == [] and s.escrituras == []


def test_ap_ausente_solo_reasocia_y_espera_entre_intentos() -> None:
    s, reloj = SistemaFalso(), Reloj()
    p = Politica(s, CFG, reloj)
    assert p.actuar(Estado.AP_AUSENTE) is not None
    assert p.actuar(Estado.AP_AUSENTE) is None  # dentro de espera_ap
    reloj.t += CFG.espera_ap + 1
    assert p.actuar(Estado.AP_AUSENTE) is not None
    assert not any("pci" in r or "fw_crash" in r for r, _ in s.escrituras)
    assert not s.ordeno("modprobe")


def test_zombi_escala_hasta_el_remedio_que_funciona() -> None:
    s = SistemaFalso()
    s.puerta = s.internet = False

    def revive() -> bool:  # el reinicio de firmware devuelve el trafico
        s.puerta = s.internet = True
        return True

    s.al_escribir[f"{DEBUGFS}/fw_crash"] = revive
    d = Politica(s, CFG).actuar(Estado.ZOMBI)
    assert d is not None and d.ok and d.paso == "reiniciar firmware" and d.fallidos == ("reasociar",)
    assert not s.ordeno("modprobe", "-r")  # no hizo falta recargar el modulo


def test_tope_de_acciones_de_hardware_por_hora() -> None:
    s, reloj = SistemaFalso(), Reloj()
    s.puerta = s.internet = False
    p = Politica(s, replace(CFG, max_resets_hora=2), reloj)
    p.actuar(Estado.FIRMWARE)  # 3 escalones de hardware, solo 2 con cupo
    assert len(p.usos_hw) == 2
    antes = len(s.escrituras)
    p.actuar(Estado.FIRMWARE)
    assert len(s.escrituras) == antes  # sin cupo no toca el hardware
    reloj.t += 3601
    assert p.cupo()


def test_modo_observar_no_ejecuta_remedios() -> None:
    s = SistemaFalso()
    d = Politica(s, replace(CFG, modo="observar")).actuar(Estado.ZOMBI)
    assert d is not None and not d.ok and s.ordenes == [] and s.escrituras == []


def test_reinicio_de_firmware_usa_fw_crash_del_debugfs_de_rtw88() -> None:
    s = SistemaFalso()
    assert acciones.reiniciar_firmware(s, CFG)
    assert (f"{DEBUGFS}/fw_crash", "1") in s.escrituras


def test_reinicio_de_firmware_falla_si_el_chip_no_vuelve() -> None:
    s = SistemaFalso()
    s.firmware = False
    assert not acciones.reiniciar_firmware(s, CFG)


def test_reset_pci_desliga_el_driver_si_el_bus_no_responde() -> None:
    s = SistemaFalso()
    s.al_escribir[f"/sys/bus/pci/devices/{CFG.pci}/remove"] = lambda: False
    assert acciones.reset_pci(s, CFG)
    assert ("/sys/bus/pci/drivers/rtw88_8821ce/bind", CFG.pci) in s.escrituras


def test_con_lockdown_salta_el_reinicio_suave_sin_gastar_cupo() -> None:
    s = SistemaFalso()
    s.archivos["/sys/kernel/security/lockdown"] = "none [integrity] confidentiality"
    s.puerta = s.internet = False

    def revive(o: list[str]) -> "Resultado":
        if o[:2] == ["modprobe", CFG.modulo]:
            s.puerta = s.internet = True
        return Resultado(0)

    s.al_correr["modprobe"] = revive
    p = Politica(s, CFG)
    d = p.actuar(Estado.FIRMWARE)
    assert d is not None and d.ok and d.paso == "recargar modulo"
    assert len(p.usos_hw) == 1  # solo la recarga gasto cupo
    assert not any(r.endswith("fw_crash") for r, _ in s.escrituras)


def test_el_tope_sobrevive_a_un_reinicio_del_demonio() -> None:
    s, reloj, usos = SistemaFalso(), Reloj(), [990.0, 995.0]
    guardados: list[int] = []
    p = Politica(s, replace(CFG, max_resets_hora=3), reloj, usos=usos, al_usar=lambda: guardados.append(1))
    s.puerta = s.internet = False
    p.actuar(Estado.FIRMWARE)
    assert len(usos) == 3 and guardados == [1]  # solo quedaba un cupo y se guardo antes de usarlo


def test_reset_pci_vuelve_a_buscar_la_tarjeta_que_quedo_fuera_del_bus() -> None:
    s = SistemaFalso()
    del s.archivos[f"/sys/bus/pci/devices/{CFG.pci}/vendor"]  # un intento anterior la quito
    assert acciones.reset_pci(s, CFG)
    rutas = [r for r, _ in s.escrituras]
    assert "/sys/bus/pci/rescan" in rutas and f"/sys/bus/pci/devices/{CFG.pci}/remove" not in rutas


def test_tras_falla_del_proveedor_no_toca_el_hardware() -> None:
    # 2026-10-26 18:03: el router fallo (otro equipo tambien perdio la wifi) y un supervisor recargo el modulo
    s, reloj = SistemaFalso(), Reloj()
    s.puerta = s.internet = False
    p = Politica(s, CFG, reloj)
    assert p.actuar(Estado.PROVEEDOR) is None
    reloj.t += 60
    d = p.actuar(Estado.DESASOCIADO)
    assert d is not None and d.fallidos == ("reasociar",) and p.usos_hw == []
    assert not s.ordeno("modprobe")
    reloj.t += CFG.espera_router + 1  # pasada la ventana, la escalera vuelve a ser completa
    p.actuar(Estado.ZOMBI)
    assert p.usos_hw != []
