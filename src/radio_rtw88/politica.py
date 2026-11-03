"""Politica: que remedios corresponden a cada causa y cuanto se permite tocar el hardware.

Los remedios van del mas suave al mas fuerte; con_respaldo los prueba en orden hasta que uno devuelve
la red. Los que tocan el hardware gastan un cupo por hora: sin cupo se omiten y se avisa una vez.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from . import acciones, cerrojo
from .config import Config
from .diagnostico import Estado
from .intentos import Desenlace, Paso, con_respaldo
from .sistema import Sistema
from .sondas import debugfs_escribible

log = logging.getLogger(__name__)
Remedio = Callable[[Sistema, Config], bool]
HW: dict[str, Remedio] = {
    "reiniciar firmware": acciones.reiniciar_firmware,
    "recargar modulo": acciones.recargar_modulo,
    "reset pci": acciones.reset_pci,
}
ESCALERA: dict[Estado, tuple[str, ...]] = {
    Estado.DESASOCIADO: ("reasociar", "reiniciar firmware", "recargar modulo"),
    Estado.ZOMBI: ("reasociar", "reiniciar firmware", "recargar modulo", "reset pci"),
    Estado.FIRMWARE: ("reiniciar firmware", "recargar modulo", "reset pci"),
    Estado.SIN_INTERFAZ: ("reset pci", "recargar modulo"),
    Estado.AP_AUSENTE: ("reasociar",),  # sin tocar el hardware: el router no esta
}


class Politica:
    def __init__(
        self,
        s: Sistema,
        cfg: Config,
        reloj: Callable[[], float] = time.time,
        usos: list[float] | None = None,
        al_usar: Callable[[], object] = lambda: None,
    ) -> None:
        """usos y al_usar vienen del registro: el tope por hora sobrevive a reinicios del demonio."""
        self.s, self.cfg, self.reloj, self.al_usar = s, cfg, reloj, al_usar
        self.usos_hw: list[float] = [] if usos is None else usos
        self.ultimo_ap = -1e9
        self.ultimo_proveedor = -1e9
        self.debugfs_ok = debugfs_escribible(s)  # sin el, no hay reinicio suave del firmware

    def cupo(self) -> bool:
        ahora = self.reloj()
        self.usos_hw[:] = [t for t in self.usos_hw if 0 <= ahora - t <= 3600]
        return len(self.usos_hw) < self.cfg.max_resets_hora

    def _paso(self, nombre: str) -> Paso:
        if nombre == "reasociar":
            return nombre, lambda: acciones.reasociar(self.s, self.cfg)
        remedio = HW[nombre]

        def con_cupo() -> bool:
            if nombre == "reiniciar firmware" and not self.debugfs_ok:
                log.info("'%s' no disponible (kernel en lockdown por Secure Boot): sigue el respaldo", nombre)
                return False
            if not self.cupo():
                log.warning(
                    "'%s' omitido: ya van %d acciones de hardware en la ultima hora",
                    nombre,
                    self.cfg.max_resets_hora,
                )
                return False
            self.usos_hw.append(self.reloj())
            self.al_usar()  # se guarda antes de tocar el hardware: si el demonio muere, cuenta igual
            return remedio(self.s, self.cfg)

        return nombre, con_cupo

    def actuar(self, estado: Estado) -> Desenlace | None:
        """Aplica la escalera de la causa. None si la causa no pide accion (o toca esperar)."""
        if estado is Estado.PROVEEDOR:
            self.ultimo_proveedor = self.reloj()
        nombres = ESCALERA.get(estado)
        if nombres and self.reloj() - self.ultimo_proveedor < self.cfg.espera_router:
            # el router ya venia fallando: perder la puerta o la asociacion es suyo, no del radio
            # (2026-10-26 un router fallo para todos y un supervisor recargo el modulo sin motivo)
            nombres = tuple(n for n in nombres if n not in HW)
        if not nombres:
            return None
        if estado is Estado.AP_AUSENTE:
            if self.reloj() - self.ultimo_ap < self.cfg.espera_ap:
                return None
            self.ultimo_ap = self.reloj()
        if self.cfg.modo == "observar":
            log.info("modo observar: para '%s' aplicaria %s", estado, " -> ".join(nombres))
            return Desenlace(False, None, ())
        with cerrojo.exclusivo(esperar=False) as libre:
            if not libre:
                return None
            return con_respaldo(f"recuperar {estado}", [self._paso(n) for n in nombres])
