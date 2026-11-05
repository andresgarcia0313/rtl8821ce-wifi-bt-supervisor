"""Perfiles de energia: ahorro adaptativo de la wifi, potencia maxima con tope solo por calor, Bluetooth."""

from dataclasses import replace

from falso import SistemaFalso
from radio_rtw88 import energia
from radio_rtw88.config import Config
from radio_rtw88.sistema import Resultado

C = Config()
RX, TX = f"/sys/class/net/{C.iface}/statistics/rx_packets", f"/sys/class/net/{C.iface}/statistics/tx_packets"


class Portatil(SistemaFalso):
    def __init__(self) -> None:
        super().__init__()
        self.ahorro = "off"
        self.archivos |= {
            "/sys/class/power_supply/AC/online": "1\n",
            "/sys/class/power_supply/BAT0/capacity": "90\n",
        }
        self.archivos |= {RX: "1000\n", TX: "1000\n"}
        self.carpetas["/sys/class/hwmon"] = ["hwmon0", "hwmon1"]
        self.archivos |= {
            "/sys/class/hwmon/hwmon0/name": "acpitz\n",
            "/sys/class/hwmon/hwmon0/temp1_input": "70000\n",
        }
        self.archivos |= {
            "/sys/class/hwmon/hwmon1/name": "nvme\n",
            "/sys/class/hwmon/hwmon1/temp1_input": "99000\n",
        }
        self.topes: list[list[str]] = []

    def correr(self, orden: list[str], tope: float = 20) -> Resultado:
        if orden[-2:] == ["get", "power_save"]:
            return Resultado(0, f"Power save: {self.ahorro}\n")
        if orden[-3:-1] == ["set", "power_save"]:
            self.ahorro = orden[-1]
            return Resultado(0)
        if "sar_specs" in orden:
            self.topes.append(orden[6:])
            return Resultado(0)
        return super().correr(orden, tope)

    def trafico(self, paquetes: int) -> None:
        self.archivos[RX] = f"{int(self.archivos[RX]) + paquetes}\n"


class Reloj:
    t = 100.0

    def __call__(self) -> float:
        return self.t


def nuevo(**cambios: object) -> tuple[energia.Energia, Portatil, Reloj, list[dict[str, object]]]:
    s, reloj, notas = Portatil(), Reloj(), []
    e = energia.Energia(s, replace(C, **cambios), lambda tipo, **d: notas.append(d), reloj)  # type: ignore[arg-type]
    return e, s, reloj, notas


def test_con_cargador_rinde_al_maximo_sin_ahorro_y_con_bluetooth_rapido() -> None:
    e, s, _, notas = nuevo()
    s.ahorro = "on"  # otro programa lo encendio
    e.vigilar()
    assert s.ahorro == "off" and notas == []  # el perfil del arranque no llena la bitacora
    assert s.ordeno("hciconfig", C.bt_hci, "pageparms", "18:256")


def test_en_bateria_equilibrado_reposa_tras_un_minuto_quieto_y_despierta_con_trafico() -> None:
    e, s, reloj, _ = nuevo()
    s.archivos["/sys/class/power_supply/AC/online"] = "0\n"
    e.vigilar()
    assert s.ordeno("hciconfig", C.bt_hci, "pageparms", "18:2048")
    for _ in range(5):  # 50 s con 5 paquetes por segundo: aun no reposa
        reloj.t += 10
        s.trafico(50)
        e.vigilar()
    assert s.ahorro == "off"
    reloj.t += 20
    s.trafico(100)
    e.vigilar()
    assert s.ahorro == "on"  # un minuto casi sin trafico
    reloj.t += 10
    s.trafico(300)  # 30 por segundo: zona intermedia, no cambia
    e.vigilar()
    assert s.ahorro == "on"
    reloj.t += 10
    s.trafico(5000)  # 500 por segundo: despierta en el acto
    e.vigilar()
    assert s.ahorro == "off"


def test_el_perfil_ahorro_tambien_despierta_con_mucho_trafico() -> None:
    e, s, reloj, _ = nuevo(perfil_energia="ahorro")
    e.vigilar()
    reloj.t += 60
    s.trafico(600)
    e.vigilar()
    reloj.t += 10
    s.trafico(10)
    e.vigilar()
    assert s.ahorro == "on"
    reloj.t += 10
    s.trafico(5000)
    e.vigilar()
    assert s.ahorro == "off"


def test_radio_nueva_vuelve_a_poner_el_tope_por_calor() -> None:
    e, s, _, _ = nuevo()
    s.archivos["/sys/class/hwmon/hwmon0/temp1_input"] = "95000\n"
    e.vigilar()
    e.radio_nueva()
    assert len(s.topes) == 2 and e.ahorro is None


def test_bateria_baja_pasa_a_ahorro() -> None:
    e, s, reloj, notas = nuevo()
    s.archivos["/sys/class/power_supply/AC/online"] = "0\n"
    s.archivos["/sys/class/power_supply/BAT0/capacity"] = "12\n"
    e.vigilar()
    reloj.t += 70
    e.vigilar()
    assert s.ahorro == "on" and e.perfil == "ahorro"
    s.archivos["/sys/class/power_supply/AC/online"] = "1\n"
    e.vigilar()
    assert s.ahorro == "off" and notas[-1]["perfil"] == "rendimiento"


def test_perfil_fijo_de_la_configuracion_manda() -> None:
    e, s, reloj, _ = nuevo(perfil_energia="ahorro")
    e.vigilar()
    reloj.t += 70
    e.vigilar()  # sin trafico durante mas de un minuto
    assert s.ahorro == "on"


def test_potencia_maxima_y_tope_solo_al_recalentarse() -> None:
    e, s, _, notas = nuevo()
    e.vigilar()
    assert s.topes == []  # 70 grados: sin tope (el disco a 99 no cuenta)
    s.archivos["/sys/class/hwmon/hwmon0/temp1_input"] = "93000\n"
    e.vigilar()
    assert s.topes[-1] == [f"{i}:{C.potencia_calor * 4}" for i in range(energia.RANGOS_SAR)]
    s.archivos["/sys/class/hwmon/hwmon0/temp1_input"] = "84000\n"
    e.vigilar()
    assert len(s.topes) == 1  # entre los dos umbrales no cambia
    s.archivos["/sys/class/hwmon/hwmon0/temp1_input"] = "70000\n"
    e.vigilar()
    assert s.topes[-1] == [f"{i}:{energia.SIN_TOPE}" for i in range(energia.RANGOS_SAR)]
    assert notas[-1]["tope_dbm"] is None


def test_en_modo_observar_no_toca_nada() -> None:
    e, s, _, _ = nuevo(modo="observar")
    s.ahorro = "on"
    e.vigilar()
    assert s.ahorro == "on" and not s.ordeno("hciconfig")


def test_la_quietud_se_cuenta_de_nuevo_tras_trafico_intermedio() -> None:
    e, s, reloj, _ = nuevo()
    s.archivos["/sys/class/power_supply/AC/online"] = "0\n"
    e.vigilar()
    reloj.t += 10
    s.trafico(10)  # quieto
    e.vigilar()
    for _ in range(60):  # 10 min con trafico intermedio (30 por segundo)
        reloj.t += 10
        s.trafico(300)
        e.vigilar()
    reloj.t += 10
    s.trafico(10)  # vuelve a estar quieto: aun no pasan 60 s seguidos
    e.vigilar()
    assert s.ahorro == "off"


def test_modo_baja_latencia_no_deja_reposar_durante_un_juego_en_bateria() -> None:
    e, s, reloj, notas = nuevo(perfil_energia="ahorro")
    contador = {"n": 0}

    def salida(_o: list[str]) -> Resultado:
        return Resultado(
            0,
            f'\tudp dport 3074 counter packets {contador["n"]} bytes 1 jump urgente comment "tiempo-real"\n',
        )

    s.al_correr["nft"] = salida
    e.vigilar()
    reloj.t += 70
    e.vigilar()
    assert s.ahorro == "on"  # sin juego, reposa
    for _ in range(3):  # juego: 30 paquetes por segundo de tiempo real con poco trafico total
        reloj.t += 10
        contador["n"] += 300
        e.vigilar()
    assert s.ahorro == "off" and any(n.get("baja_latencia") for n in notas)
    for _ in range(9):  # 90 s sin juego: el modo termina y vuelve a reposar
        reloj.t += 10
        e.vigilar()
    assert s.ahorro == "on" and notas[-1].get("baja_latencia") is False
