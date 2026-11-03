"""Comprobaciones y esperas comunes a los remedios: la wifi cursa trafico, esperar con tope, levantarla."""

from __future__ import annotations

from collections.abc import Callable

from . import intentos
from .config import Config
from .intentos import con_respaldo
from .sistema import Sistema
from .sondas import enlace, ping


def red_ok(s: Sistema, cfg: Config) -> bool:
    """Asociada y con respuesta de la puerta de enlace o de internet, siempre por la interfaz wifi."""
    return enlace(s, cfg)[0] and (ping(s, cfg, cfg.puerta) or any(ping(s, cfg, d) for d in cfg.internet))


def pausa(s: Sistema, segundos: float) -> bool:
    """Duerme y devuelve True, para encadenar esperas dentro de una condicion."""
    s.dormir(segundos)
    return True


def esperar(s: Sistema, cond: Callable[[], bool], segundos: float, paso: float = 2) -> bool:
    """Repite la condicion hasta que se cumpla o se agote el tiempo (nunca espera sin limite)."""
    for _ in range(max(1, int(segundos / paso))):
        intentos.latido()  # cada sondeo demuestra al watchdog que la recuperacion avanza
        if cond():
            return True
        s.dormir(paso)
    return cond()


def interfaz_presente(s: Sistema, cfg: Config) -> bool:
    return esperar(s, lambda: s.leer(f"/sys/class/net/{cfg.iface}/operstate") is not None, 20)


def levantar(s: Sistema, cfg: Config) -> bool:
    """Levanta la conexion y espera trafico; cada orden respalda a la anterior."""

    def con(orden: list[str], espera: float) -> Callable[[], bool]:
        return lambda: s.correr(orden, tope=40).ok and esperar(s, lambda: red_ok(s, cfg), espera)

    pasos = [
        ("nmcli con up", con(["nmcli", "connection", "up", cfg.conexion], 10)),
        ("nmcli device connect", con(["nmcli", "device", "connect", cfg.iface], 10)),
        ("wpa_cli reassociate", con(["wpa_cli", "-i", cfg.iface, "reassociate"], 20)),
    ]
    return con_respaldo("levantar wifi", pasos).ok
