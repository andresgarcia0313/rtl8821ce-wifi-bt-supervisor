"""Canal congestionado: reconocer por que se pierden paquetes y aplicar la tecnica que sirve en cada caso.

Cada minuto, 5 pings rapidos al router por la wifi dicen perdida y demora del aire. Con la senal:
- senal baja (menos de -75 dBm): es distancia; lo atiende la eleccion de banda (2,4 GHz llega mas lejos);
- buena senal con perdida o demora alta: es congestion o interferencia de otras redes del canal. Se enciende
  RTS/CTS (la tarjeta reserva el canal antes de cada envio grande): choca menos con redes que no se oyen
  entre si (nodo oculto). Se apaga tras 10 min de canal limpio, porque en canal libre solo agrega espera.
rtw88 no informa reintentos por paquete (el control de tasa vive en el firmware): la medida es el ping.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from . import sondas
from .config import Config
from .intentos import resiste, valor
from .sistema import Sistema
from .sondas import Medida

log = logging.getLogger(__name__)
CADA = 60.0
LEJOS = -75  # dBm
DEMORA_MAX = 80.0  # ms: un pico asi en 5 pings al router es aire ocupado
DEMORA_MEDIA = 25.0  # ms
LIMPIO_ANTES = 600.0  # segundos de canal limpio antes de apagar RTS/CTS
UMBRAL_RTS = 500  # bytes: los envios mas grandes reservan el canal


@resiste(valor(None))
def muestra(s: Sistema, cfg: Config) -> tuple[float, float, float] | None:
    """(perdida %, demora media ms, demora maxima ms) de 5 pings al router por la wifi."""
    r = s.correr(["ping", "-c5", "-i0.2", "-W1", "-q", "-I", cfg.iface, cfg.puerta], tope=8)
    perdida = re.search(r"([\d.]+)% packet loss", r.salida)
    demora = re.search(r"= [\d.]+/([\d.]+)/([\d.]+)/", r.salida)
    if perdida is None:
        return None
    media, maxima = (float(demora.group(1)), float(demora.group(2))) if demora else (0.0, 0.0)
    return float(perdida.group(1)), media, maxima


@resiste(valor("limpio"))
def clasificar(senal: int | None, datos: tuple[float, float, float], arp_ok: bool = False) -> str:
    """Una perdida sin demora que el router si contesta por ARP es del router (ignora pings a ratos), no
    del aire: solo cuenta como congestion si la demora sube o si tampoco contesta ARP."""
    perdida, media, maxima = datos
    if senal is not None and senal < LEJOS:
        return "lejos"
    if maxima > DEMORA_MAX or media > DEMORA_MEDIA or (perdida > 0 and not arp_ok):
        return "congestionado"
    return "limpio"


@resiste(valor(False))
def poner_rts(s: Sistema, cfg: Config, encendido: bool) -> bool:
    phy = (s.leer(f"/sys/class/net/{cfg.iface}/phy80211/name") or "").strip()
    valor_rts = str(UMBRAL_RTS) if encendido else "off"
    return bool(phy) and s.correr(["iw", "phy", phy, "set", "rts", valor_rts], tope=5).ok


class Canal:
    def __init__(
        self,
        s: Sistema,
        cfg: Config,
        anotar: Callable[..., object] = lambda *a, **k: None,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.s, self.cfg, self.anotar, self.reloj = s, cfg, anotar, reloj
        self.ultimo = -1e9
        self.estado = "limpio"
        self.rts = False
        self.limpio_desde: float | None = None

    @resiste(valor(None))
    def vigilar(self, m: Medida) -> None:
        if not self.cfg.canal_adaptativo or not m.asociado or self.reloj() - self.ultimo < CADA:
            return
        self.ultimo = self.reloj()
        datos = muestra(self.s, self.cfg)
        if datos is None:
            return
        arp_ok = datos[0] > 0 and sondas.arp(self.s, self.cfg, self.cfg.puerta)
        nuevo = clasificar(m.senal, datos, arp_ok)
        if nuevo != self.estado:
            texto = f"canal {self.estado} -> {nuevo} (senal {m.senal} dBm, perdida {datos[0]:.0f} %, "
            texto += f"demora media {datos[1]:.0f} ms, maxima {datos[2]:.0f} ms)"
            log.info(texto)
            self.anotar(
                "canal", estado=nuevo, senal=m.senal, perdida=datos[0], demora_max=datos[2], texto=texto
            )
            self.estado = nuevo
        if nuevo != "limpio":
            self.limpio_desde = None
        elif self.limpio_desde is None:
            self.limpio_desde = self.reloj()
        if self.cfg.modo == "observar":
            return
        if nuevo == "congestionado" and not self.rts:
            self.cambiar_rts(True)
        elif self.rts and self.limpio_desde is not None and self.reloj() - self.limpio_desde >= LIMPIO_ANTES:
            self.cambiar_rts(False)

    @resiste(valor(None))
    def cambiar_rts(self, encendido: bool) -> None:
        if poner_rts(self.s, self.cfg, encendido):
            self.rts = encendido
            texto = "RTS/CTS encendido: canal congestionado" if encendido else "RTS/CTS apagado: canal limpio"
            self.anotar("canal", rts=encendido, texto=texto)
