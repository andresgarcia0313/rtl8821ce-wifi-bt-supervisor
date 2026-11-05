"""Vigilancia del Bluetooth dentro del demonio: si deja de responder a un comando HCI lo confirma, lo repara
con la escalera de bluetooth.reparar y anota cada falla en la bitacora con su evidencia.

El Bluetooth de un servidor puede llevar un canal de rescate (NAP): repararlo corta esos enlaces unos
segundos, asi que nunca se actua por una sola lectura. Los remedios fallidos seguidos espacian los
reintentos hasta 12 h y el aviso critico sale una sola vez por episodio (contador en disco: sobrevive a
reinicios del demonio y del equipo).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from . import bluetooth, cerrojo, servicio, sondas
from .config import Config
from .episodios import Episodios
from .sistema import Sistema

log = logging.getLogger(__name__)
CADA_BT = 300  # segundos entre revisiones con el Bluetooth sano
CONFIRMAR_BT = 30  # tras una lectura mala, segundos hasta la segunda que confirma la falla
TOPE_BT = 43200
BT_DEBIL = -30  # dB por debajo del rango ideal del receptor: enlace en riesgo de cortes


class VigiaBt:
    def __init__(
        self,
        s: Sistema,
        cfg: Config,
        episodios: Episodios,
        silenciar: Callable[[float], object] = lambda _s: None,
    ) -> None:
        self.s, self.cfg, self.episodios, self.silenciar = s, cfg, episodios, silenciar
        self.ultimo = (
            time.monotonic()
        )  # primera revision a los CADA_BT s: tras arrancar el hci tarda en estar
        self.sospecha = False  # la ultima lectura fallo y falta confirmarla
        self.debiles: dict[str, bool] = {}  # equipos conectados con senal debil
        self._fallos_ruta = Path(cfg.estado_dir) / "bt-fallos"
        try:
            self.fallos = int(self._fallos_ruta.read_text())
        except (OSError, ValueError):
            self.fallos = 0
        # primera revision a los CADA_BT s, aunque haya fallos guardados: tras arrancar el hci tarda en estar
        self.ultimo = time.monotonic() - self.espera() + CADA_BT

    def espera(self) -> float:
        if self.sospecha:
            return CONFIRMAR_BT
        return float(min(CADA_BT * 2**self.fallos, TOPE_BT))

    def revisar_ya(self) -> None:
        """Un error del Bluetooth en el kernel adelanta la revision a CONFIRMAR_BT s, solo con el Bluetooth
        sano: nunca salta la espera creciente tras remedios fallidos (evita reparar en bucle)."""
        if self.fallos == 0:
            self.ultimo = min(self.ultimo, time.monotonic() - self.espera() + CONFIRMAR_BT)

    def vigilar(self) -> None:
        if not self.cfg.bluetooth or time.monotonic() - self.ultimo < self.espera():
            return
        self.ultimo = time.monotonic()
        if sondas.apagada_a_proposito(self.s, "bluetooth"):
            if self.s.leer(bluetooth.marca_rfkill(self.cfg)) is None:
                self.sospecha = False  # apagado por el usuario: se respeta
                return
            log.warning("el Bluetooth quedo bloqueado por una reparacion interrumpida: lo desbloqueo")
            if self.s.correr(["rfkill", "unblock", "bluetooth"]).ok:
                self.s.correr(["rm", "-f", bluetooth.marca_rfkill(self.cfg)])
        vivo = bluetooth.responde(self.s, self.cfg)
        if vivo is None:  # sin hcitool o sin bluetoothctl no se sabe: nunca se repara a ciegas
            log.warning("no se pudo medir el Bluetooth (falta hcitool o bluetoothctl)")
            return
        if vivo:
            self.sospecha = False
            self._recuperado()
            self._senales()
            return
        if not self.sospecha:
            self.sospecha = True  # una sola lectura no basta: se confirma CONFIRMAR_BT s despues
            return
        self.sospecha = False
        self.episodios.bt("falla", "no responde a un comando HCI (confirmado)", True)
        if self.cfg.modo == "observar":
            log.info("modo observar: el Bluetooth no responde; aplicaria la escalera de reparacion")
            return
        with cerrojo.exclusivo(esperar=False) as libre:  # si otro actua, se reintenta en la proxima ronda
            if not libre:
                return
            self.silenciar(180)  # los mensajes del kernel que provoca la reparacion no son fallas nuevas
            ok, paso = bluetooth.reparar(self.s, self.cfg)
        self.episodios.bt("remedio", f"reparado con '{paso}'" if ok else "ningun paso lo reparo")
        if ok:
            self._recuperado()
            return
        self._anotar(self.fallos + 1)
        if self.fallos == 1:
            servicio.avisar(
                "critical",
                "el Bluetooth no responde; reintento cada vez mas espaciado. Ver la bitacora de eventos",
            )

    def _senales(self) -> None:
        """Anota cuando un enlace se debilita o se recupera (no en cada revision)."""
        for direccion, db in bluetooth.senal_enlaces(self.s, self.cfg).items():
            debil = db <= BT_DEBIL
            if debil != self.debiles.get(direccion, False):
                self.debiles[direccion] = debil
                estado = "debil" if debil else "recuperado"
                self.episodios.bt(
                    "senal", f"enlace con {direccion} {estado}: {db} dB respecto del rango ideal"
                )

    def _recuperado(self) -> None:
        if self.fallos:
            servicio.avisar("recovered", "el Bluetooth volvio a responder")
            self._anotar(0)

    def _anotar(self, fallos: int) -> None:
        self.fallos = fallos
        try:
            self._fallos_ruta.parent.mkdir(parents=True, exist_ok=True)
            self._fallos_ruta.write_text(str(fallos))
        except OSError as exc:
            log.error("guardar fallos del Bluetooth: %s", exc)
