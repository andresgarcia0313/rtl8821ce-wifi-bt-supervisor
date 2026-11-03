"""Vigia del cable USB del celular: avisa una vez si el respaldo se perdio sin que nadie lo note.

Si el puerto USB se reinicia (reconexion, reinicio del equipo), Android apaga el anclaje: la interfaz
sigue ahi pero el celular ya no entrega direccion por DHCP, y la wifi queda sin respaldo. Solo se
puede reactivar desde el celular, asi que lo unico util es avisar (una vez por episodio).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from . import servicio
from .escenario import interfaz_anclaje
from .sistema import Sistema

log = logging.getLogger(__name__)
GRACIA = 600.0  # segundos sin direccion antes de avisar (DHCP del celular tarda; un cambio de red tambien)


class VigiaCable:
    def __init__(
        self,
        s: Sistema,
        anotar: Callable[..., object] = lambda *a, **k: None,
        reloj: Callable[[], float] = time.monotonic,
        anclaje: Callable[[], str | None] = interfaz_anclaje,
    ) -> None:
        self.s, self.anotar, self.reloj, self.anclaje = s, anotar, reloj, anclaje
        self.sin_ip_desde: float | None = None
        self.avisado = False

    def _con_ip(self, iface: str) -> bool:
        r = self.s.correr(["ip", "-4", "-o", "addr", "show", "dev", iface], tope=5)
        return r.ok and " inet " in r.salida

    def vigilar(self) -> None:
        iface = self.anclaje()
        if iface is None or self._con_ip(iface):  # sin cable no hay nada que vigilar; con IP esta bien
            if self.avisado:
                servicio.avisar("recovered", "el cable USB del celular vuelve a dar internet de respaldo")
                self.anotar("cable", accion="anclaje de vuelta", interfaz=iface)
            self.sin_ip_desde, self.avisado = None, False
            return
        if self.sin_ip_desde is None:
            self.sin_ip_desde = self.reloj()
        if not self.avisado and self.reloj() - self.sin_ip_desde >= GRACIA:
            self.avisado = True
            log.warning(
                "cable USB %s sin direccion hace %.0f s: el anclaje del celular esta apagado", iface, GRACIA
            )
            self.anotar("cable", accion="anclaje apagado", interfaz=iface)
            servicio.avisar(
                "critical",
                "el cable USB del celular no da direccion: activa de nuevo el anclaje USB en el celular",
            )
