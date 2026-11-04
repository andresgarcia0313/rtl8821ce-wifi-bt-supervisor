"""Perfiles de NetworkManager del respaldo de internet: consultar, subir y bajar, cada orden con tope."""

from __future__ import annotations

from .config import Config
from .escenario import interfaz_anclaje
from .intentos import resiste, valor
from .sistema import Sistema


class Perfiles:
    def __init__(self, s: Sistema, cfg: Config) -> None:
        self.s, self.cfg = s, cfg

    @resiste(valor(None))
    def nm(self, *orden: str, tope: float = 20) -> str | None:
        r = self.s.correr(["nmcli", *orden], tope=tope)
        return r.salida.strip() if r.ok else None

    @resiste(valor(False))
    def en_celular(self) -> bool:
        return self.nm("-g", "GENERAL.CONNECTION", "device", "show", self.cfg.iface) == self.cfg.celular

    @resiste(valor(False))
    def bt_activo(self) -> bool:
        return self.nm("-g", "GENERAL.STATE", "connection", "show", self.cfg.bt_celular) == "activated"

    @resiste(valor(""))
    def mac_bt(self) -> str:
        """-g escapa los dos puntos de la direccion (CC\\:62...)."""
        return (self.nm("-g", "bluetooth.bdaddr", "connection", "show", self.cfg.bt_celular) or "").replace(
            "\\", ""
        )

    @resiste(valor(False))
    def visible(self, ssid: str) -> bool:
        orden = ("-t", "-f", "SSID", "device", "wifi", "list", "ifname", self.cfg.iface, "--rescan", "yes")
        return ssid in (self.nm(*orden, tope=30) or "").splitlines()

    @resiste(valor(False))
    def subir(self, perfil: str, tope: float = 60) -> bool:
        return self.nm("connection", "up", perfil, tope=tope) is not None

    @resiste(valor(False))
    def bajar(self, perfil: str) -> bool:
        return self.nm("connection", "down", perfil) is not None

    @resiste(valor(False))
    def cable_util(self) -> bool:
        """Hay anclaje USB del celular (por driver) y sale a internet por el."""
        iface = interfaz_anclaje()
        return iface is not None and any(
            self.s.correr(["ping", "-c1", "-W2", "-I", iface, d], tope=5).ok for d in self.cfg.internet[:2]
        )
