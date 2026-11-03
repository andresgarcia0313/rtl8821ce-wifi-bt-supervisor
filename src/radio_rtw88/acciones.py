"""Remedios de la wifi, de menor a mayor fuerza. Cada uno devuelve True solo si la wifi volvio a cursar datos.

Cada remedio tiene un metodo alterno por si el preferido falla (patron de intentos.con_respaldo).
"""

from __future__ import annotations

from .config import Config
from .intentos import con_respaldo
from .red import esperar, interfaz_presente, levantar, pausa, red_ok
from .sistema import Sistema
from .sondas import chip_vivo, debugfs


def reasociar(s: Sistema, cfg: Config) -> bool:
    s.correr(["nmcli", "device", "disconnect", cfg.iface], tope=20)
    s.dormir(1)
    return levantar(s, cfg)


def reiniciar_firmware(s: Sistema, cfg: Config) -> bool:
    """Recuperacion de firmware del propio rtw88 (escribir en debugfs fw_crash): el driver la hace sola tras
    un crash real. Solo existe sin lockdown; con Secure Boot la politica la omite."""
    carpeta = debugfs(s, cfg)
    return (
        carpeta is not None
        and s.escribir(f"{carpeta}/fw_crash", "1")
        and pausa(s, 5)
        and esperar(s, lambda: chip_vivo(s, cfg), 15)
        and (esperar(s, lambda: red_ok(s, cfg), 12) or levantar(s, cfg))
    )


def presente(s: Sistema, cfg: Config) -> bool:
    """El dispositivo PCI de la tarjeta sigue en el bus."""
    return s.leer(f"/sys/bus/pci/devices/{cfg.pci}/vendor") is not None


def recargar_modulo(s: Sistema, cfg: Config) -> bool:
    if not presente(s, cfg):  # sin dispositivo no hay que recargar: buscarlo en el bus
        s.escribir("/sys/bus/pci/rescan", "1")
    s.correr(["modprobe", "-r", cfg.modulo], tope=30)  # baja tambien rtw88_pci y rtw88_core si quedan libres
    s.dormir(2)
    if not s.correr(["modprobe", cfg.modulo], tope=30).ok or not interfaz_presente(s, cfg):
        return False
    return levantar(s, cfg)


def reset_pci(s: Sistema, cfg: Config) -> bool:
    """Quita el dispositivo del bus y lo vuelve a buscar; si el bus no responde, desliga y liga el driver."""
    driver = f"/sys/bus/pci/drivers/{cfg.modulo}"

    def por_bus() -> bool:
        # si un intento anterior lo quito y el rescan fallo, el dispositivo ya no esta: solo buscarlo
        if presente(s, cfg) and not s.escribir(f"/sys/bus/pci/devices/{cfg.pci}/remove", "1"):
            return False
        return pausa(s, 3) and s.escribir("/sys/bus/pci/rescan", "1")

    def por_driver() -> bool:
        s.escribir(f"{driver}/unbind", cfg.pci)
        return pausa(s, 2) and s.escribir(f"{driver}/bind", cfg.pci)

    ok = con_respaldo("reset pci", [("remove+rescan", por_bus), ("unbind+bind", por_driver)]).ok
    return ok and interfaz_presente(s, cfg) and levantar(s, cfg)
