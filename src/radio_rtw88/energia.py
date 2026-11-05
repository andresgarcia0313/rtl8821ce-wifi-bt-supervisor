"""Perfiles de energia de la radio: rendimiento, equilibrado y ahorro, elegidos solos por cargador y bateria.

- Ahorro de la wifi sin perder paquetes: rtw88 sale del reposo (LPS) por su cuenta cuando ve trafico, y el
  reposo profundo queda desactivado (disable_lps_deep=y, ADR 0003), que es el que congela el 8821CE. En
  "equilibrado" el ahorro se enciende solo con la interfaz casi sin trafico y se apaga apenas hay trafico.
- Potencia: siempre la maxima que permite la regulacion del pais y la certificacion del equipo (que ya
  incluye el limite de exposicion SAR). Solo si el portatil se recalienta se pone un tope temporal por SAR
  (`iw phy set sar_specs`), y se quita al enfriarse: rtw88 ignora `iw set txpower`.
- Bluetooth: la conexion rapida (escaneo de pagina cada 160 ms) solo en rendimiento; en los otros perfiles
  escucha cada 1,28 s, que gasta menos y sigue aceptando al canal de rescate.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from .config import Config
from .intentos import resiste, valor
from .sistema import Sistema

log = logging.getLogger(__name__)
PERFILES = ("rendimiento", "equilibrado", "ahorro")
BATERIA_BAJA = 30  # % por debajo del cual "auto" pasa a ahorro
REPOSO_PPS = 20.0  # paquetes por segundo por debajo de los cuales la wifi puede reposar
DESPIERTA_PPS = {"equilibrado": 50.0, "ahorro": 200.0}  # por encima, el ahorro se apaga en el acto
REPOSO_ANTES = 60.0  # segundos seguidos casi sin trafico antes de encender el ahorro
SIN_TOPE = 120  # 30 dBm en cuartos de dBm: por encima del maximo del chip, no limita nada
RANGOS_SAR = 4  # rangos de frecuencia que acepta rtw88 para SAR
CADA_REVISION = 300.0


@resiste(valor("rendimiento"))
def perfil(s: Sistema, cfg: Config) -> str:
    """El perfil fijo de la configuracion o, en "auto", el que corresponde al cargador y la bateria."""
    if cfg.perfil_energia in PERFILES:
        return cfg.perfil_energia
    if (s.leer("/sys/class/power_supply/AC/online") or "1").strip() == "1":
        return "rendimiento"
    carga = (s.leer("/sys/class/power_supply/BAT0/capacity") or "100").strip()
    return "ahorro" if carga.isdigit() and int(carga) < BATERIA_BAJA else "equilibrado"


@resiste(valor(None))
def temperatura(s: Sistema) -> float | None:
    """La mas alta de los sensores del portatil (el chip wifi no expone la suya), en grados."""
    valores = []
    for nombre in s.listar("/sys/class/hwmon"):
        tipo = (s.leer(f"/sys/class/hwmon/{nombre}/name") or "").strip()
        crudo = s.leer(f"/sys/class/hwmon/{nombre}/temp1_input") if tipo in ("acpitz", "coretemp") else None
        if crudo and crudo.strip().isdigit():
            valores.append(int(crudo) / 1000)
    return max(valores) if valores else None


@resiste(valor(None))
def paquetes(s: Sistema, cfg: Config) -> int | None:
    total = 0
    for sentido in ("rx_packets", "tx_packets"):
        crudo = s.leer(f"/sys/class/net/{cfg.iface}/statistics/{sentido}")
        if crudo is None or not crudo.strip().isdigit():
            return None
        total += int(crudo)
    return total


@resiste(valor(False))
def poner_ahorro(s: Sistema, cfg: Config, encendido: bool) -> bool:
    estado = "on" if encendido else "off"
    return s.correr(["iw", "dev", cfg.iface, "set", "power_save", estado], tope=5).ok


@resiste(valor(False))
def poner_tope(s: Sistema, cfg: Config, dbm: int | None) -> bool:
    phy = (s.leer(f"/sys/class/net/{cfg.iface}/phy80211/name") or "").strip()
    cuartos = SIN_TOPE if dbm is None else dbm * 4
    rangos = [f"{i}:{cuartos}" for i in range(RANGOS_SAR)]
    return bool(phy) and s.correr(["iw", "phy", phy, "set", "sar_specs", "0", *rangos], tope=5).ok


@resiste(valor(False))
def conexion_rapida_bt(s: Sistema, cfg: Config, encendida: bool) -> bool:
    """Escucha de pagina cada 160 ms (rapida) o cada 1,28 s (la del estandar), con ventana de 11,25 ms.
    Se fija por HCI con hciconfig: btmgmt se colgaba hasta su tope en el equipo."""
    parametros = "18:256" if encendida else "18:2048"  # ventana:intervalo en ranuras de 0,625 ms
    return s.correr(["hciconfig", cfg.bt_hci, "pageparms", parametros], tope=5).ok


@resiste(valor(None))
def ahorro_actual(s: Sistema, cfg: Config) -> bool | None:
    r = s.correr(["iw", "dev", cfg.iface, "get", "power_save"], tope=5)
    hallado = re.search(r"Power save:\s*(\w+)", r.salida) if r.ok else None
    return None if hallado is None else hallado.group(1) == "on"


class Energia:
    def __init__(
        self,
        s: Sistema,
        cfg: Config,
        anotar: Callable[..., object] = lambda *a, **k: None,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.s, self.cfg, self.anotar, self.reloj = s, cfg, anotar, reloj
        self.perfil: str | None = None
        self.ahorro: bool | None = None  # lo ultimo aplicado
        self.revisado = -1e9
        self.muestra: tuple[float, int] | None = None
        self.tope: int | None = None  # dBm del tope por calor (None: sin tope)
        self.quieto_desde: float | None = None  # desde cuando la interfaz esta casi sin trafico

    @resiste(valor(None))
    def vigilar(self) -> None:
        if self.cfg.modo == "observar":
            return
        actual = perfil(self.s, self.cfg)
        if actual != self.perfil:
            log.info("perfil de energia: %s", actual)
            if self.perfil is not None:  # el del arranque va solo al journal; los cambios, a la bitacora
                self.anotar("energia", perfil=actual, texto=f"perfil de energia: {self.perfil} -> {actual}")
            if self.cfg.bluetooth:
                conexion_rapida_bt(self.s, self.cfg, actual == "rendimiento")
            self.perfil, self.revisado = actual, -1e9
        self.ajustar_ahorro(self.quiere_ahorro(actual))
        self.vigilar_calor()

    @resiste(valor(False))
    def quiere_ahorro(self, actual: str) -> bool:
        """Con histeresis: reposa tras 60 s casi sin trafico y despierta apenas el trafico sube (con mas
        margen en "ahorro"). Asi el ahorro no se enciende y apaga en cada vuelta ni frena el trafico."""
        if actual == "rendimiento":
            self.quieto_desde = None
            return False
        ahora, total = self.reloj(), paquetes(self.s, self.cfg)
        previa, self.muestra = self.muestra, (ahora, total) if total is not None else None
        if previa is None or total is None or ahora <= previa[0]:
            return bool(self.ahorro)
        pps = (total - previa[1]) / (ahora - previa[0])
        if pps > DESPIERTA_PPS[actual]:
            self.quieto_desde = None
            return False
        if pps >= REPOSO_PPS:
            self.quieto_desde = None  # la quietud debe ser seguida: se vuelve a contar
            return bool(self.ahorro)  # zona intermedia: se queda como esta
        self.quieto_desde = (
            previa[0] if self.quieto_desde is None else self.quieto_desde
        )  # quieto desde la muestra anterior
        return bool(self.ahorro) or ahora - self.quieto_desde >= REPOSO_ANTES

    @resiste(valor(None))
    def ajustar_ahorro(self, quiere: bool) -> None:
        """Aplica solo si cambia o si pasaron 5 min (otro programa, como TLP, pudo cambiarlo)."""
        if quiere == self.ahorro and self.reloj() - self.revisado < CADA_REVISION:
            return
        self.revisado = self.reloj()
        if ahorro_actual(self.s, self.cfg) != quiere and poner_ahorro(self.s, self.cfg, quiere):
            log.info(
                "ahorro de energia de la wifi: %s (perfil %s)",
                "encendido" if quiere else "apagado",
                self.perfil,
            )
        self.ahorro = quiere

    @resiste(valor(None))
    def radio_nueva(self) -> None:
        """El chip se reinicio: el ahorro se vuelve a revisar y el tope por calor, si lo habia, a poner."""
        self.ahorro, self.revisado = None, -1e9
        if self.tope is not None:
            poner_tope(self.s, self.cfg, self.tope)

    @resiste(valor(None))
    def vigilar_calor(self) -> None:
        grados = temperatura(self.s)
        if grados is None:
            return
        if self.tope is None and grados >= self.cfg.temp_max:
            self.tope = self.cfg.potencia_calor
        elif self.tope is not None and grados <= self.cfg.temp_ok:
            self.tope = None
        else:
            return
        ok = poner_tope(self.s, self.cfg, self.tope)
        texto = f"tope de potencia {self.tope} dBm por calor" if self.tope else "potencia maxima de nuevo"
        log.warning("%s (%.0f grados): %s", texto, grados, ok)
        self.anotar("potencia", grados=grados, tope_dbm=self.tope, ok=ok, texto=texto)
