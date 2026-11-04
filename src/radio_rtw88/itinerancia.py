"""Itinerancia minima: fijar la wifi al unico punto de acceso de la red y soltarla si deja de verse.

NetworkManager configura el escaneo de fondo de wpa_supplicant cada 300 s si el perfil recuerda mas de
un punto de acceso (seen-bssids), y cada escaneo saca a la tarjeta del canal: picos de ~450 ms medidos
en el equipo. Con el BSSID fijado, NetworkManager no configura escaneo de fondo. Es lo que en Windows
hacen "Sensibilidad de itinerancia: la mas baja" y "Banda preferida". Solo se fija si la red tiene un
solo punto de acceso visible (con varios, la itinerancia sirve) y con el cable de respaldo util, porque
aplicar el cambio reconecta la wifi unos segundos. Si el punto fijado deja de verse, se suelta y se
reconecta: un router nuevo no deja al equipo sin red.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from .config import Config
from .diagnostico import Estado
from .intentos import resiste, valor
from .perfiles import Perfiles
from .red import esperar, levantar, red_ok
from .sistema import Sistema

log = logging.getLogger(__name__)
SANO_ANTES = 600.0  # segundos de wifi sana antes de fijar (nunca en medio de un episodio)
REINTENTO = 6 * 3600.0  # entre intentos de fijar: evita reconectar seguido si algo sale mal
LINEA = re.compile(r"^((?:[0-9A-Fa-f]{2}\\:){5}[0-9A-Fa-f]{2}):(.*)$")


class Itinerancia:
    def __init__(
        self,
        s: Sistema,
        cfg: Config,
        anotar: Callable[..., object] = lambda *a, **k: None,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.s, self.cfg, self.anotar, self.reloj = s, cfg, anotar, reloj
        self.p = Perfiles(s, cfg)
        self.sano_desde: float | None = None
        self.ultimo_intento = -1e9

    @resiste(valor(None))
    def fijado(self) -> str | None:
        """BSSID fijado en el perfil, "" si no hay ninguno y None si no se pudo leer (no se actua)."""
        crudo = self.p.nm("-g", "802-11-wireless.bssid", "connection", "show", self.cfg.conexion)
        return None if crudo is None else crudo.replace("\\", "").upper()

    @resiste(valor(None))
    def visibles(self) -> list[str] | None:
        """BSSID que anuncian el SSID del perfil en el ultimo escaneo; None si no se pudo leer."""
        ssid = self.p.nm("-g", "802-11-wireless.ssid", "connection", "show", self.cfg.conexion)
        lista = self.p.nm("-t", "-f", "BSSID,SSID", "device", "wifi", "list", "ifname", self.cfg.iface)
        if ssid is None or lista is None:
            return None
        hallados = (LINEA.match(linea) for linea in lista.splitlines())
        return [h.group(1).replace("\\", "").upper() for h in hallados if h and h.group(2) == ssid]

    @resiste(valor(None))
    def actual(self) -> str | None:
        r = self.s.correr(["iw", "dev", self.cfg.iface, "link"], tope=5)
        hallado = re.search(r"Connected to (\S+)", r.salida) if r.ok else None
        return hallado.group(1).upper() if hallado else None

    @resiste(valor(False))
    def poner(self, bssid: str) -> bool:
        modificado = self.p.nm("connection", "modify", self.cfg.conexion, "802-11-wireless.bssid", bssid)
        return modificado is not None and levantar(self.s, self.cfg)

    @resiste(valor(None))
    def vigilar(self, estado: Estado) -> None:
        if not self.cfg.fijar_bssid or self.cfg.modo == "observar":
            return
        if estado is not Estado.SANO:
            self.sano_desde = None
            if estado in (Estado.DESASOCIADO, Estado.AP_AUSENTE):
                self.soltar_si_falta()
            return
        self.sano_desde = self.reloj() if self.sano_desde is None else self.sano_desde
        if self.reloj() - self.sano_desde >= SANO_ANTES and self.reloj() - self.ultimo_intento >= REINTENTO:
            self.fijar()

    @resiste(valor(False))
    def fijar(self) -> bool:
        self.ultimo_intento = self.reloj()
        actual, visibles = self.actual(), self.visibles()
        if self.fijado() != "" or actual is None or visibles != [actual] or not self.p.cable_util():
            return False  # ya fijado o ilegible, sin enlace, varios puntos de acceso o sin cable de respaldo
        ok = self.poner(actual) and esperar(self.s, lambda: red_ok(self.s, self.cfg), 20)
        if not ok:
            self.poner("")  # no volvio con el punto fijado: se deja como estaba
        log.info("fijar el punto de acceso %s: %s", actual, ok)
        self.anotar("itinerancia", accion="fijar", bssid=actual, ok=ok)
        return ok

    @resiste(valor(False))
    def soltar_si_falta(self) -> bool:
        fijado, visibles = self.fijado(), self.visibles()
        if not fijado or visibles is None or fijado in visibles:
            return False  # sin fijacion, escaneo ilegible o el punto fijado sigue ahi
        ok = self.soltar()
        log.warning("el punto de acceso fijado %s no se ve: se suelta (%s)", fijado, ok)
        self.anotar("itinerancia", accion="soltar", bssid=fijado, ok=ok)
        return ok

    @resiste(valor(False))
    def soltar(self) -> bool:
        """Quita la fijacion sin reconectar (la reconexion la hace el remedio que sigue). Tambien la usan
        el aviso de caida y restaurar.sh: sin el controlador vivo nadie soltaria un punto que ya no existe."""
        return self.p.nm("connection", "modify", self.cfg.conexion, "802-11-wireless.bssid", "") is not None
