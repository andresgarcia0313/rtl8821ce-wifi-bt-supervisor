"""Bluetooth Realtek por USB (btusb + btrtl): saber si responde y repararlo con el paso mas suave que sirva.

La prueba de vida es un comando HCI real (Read Local Version): `bluetoothctl show` puede decir
"Powered: yes" con el firmware trabado porque lee lo que bluetoothd tiene guardado.
Escalera: encender -> rfkill -> religar btusb (unbind/bind de sus interfaces USB). authorized=0/1 y
usbreset solo con bt_usb_profundo: en un equipo hermano, cortar el puerto USB del radio no lo trajo de
vuelta sin reiniciar, asi que esos pasos se encienden solo despues de probar que el equipo vuelve.
"""

from __future__ import annotations

import os
import re

from . import intentos
from .config import Config
from .intentos import con_respaldo, resiste, valor
from .red import esperar, pausa
from .sistema import Sistema

USB = "/sys/bus/usb/devices"
BTUSB = "/sys/bus/usb/drivers/btusb"


@resiste(valor(None))
def responde(s: Sistema, cfg: Config) -> bool | None:
    """El controlador contesta un comando HCI y bluetoothd lo tiene encendido. None: no se pudo medir
    (falta la herramienta), que nunca debe tomarse como falla del hardware."""
    hci = s.correr(["hcitool", "-i", cfg.bt_hci, "cmd", "0x04", "0x0001"], tope=10)
    if hci.rc == 127:
        return None
    if not (hci.ok and "HCI Event" in hci.salida):
        return False
    r = s.correr(["bluetoothctl", "show"], tope=10)
    if r.rc == 127:
        return None
    return r.ok and "Powered: yes" in r.salida


@resiste(lambda *_a, **_k: {})
def senal_enlaces(s: Sistema, cfg: Config) -> dict[str, int]:
    """Senal de cada equipo conectado, en dB respecto del rango ideal del receptor (0 = ideal, negativo =
    por debajo). Es lo que da el comando HCI estandar Read RSSI; este chip no mide la calidad del enlace."""
    conectados = s.correr(["bluetoothctl", "devices", "Connected"], tope=10).salida
    senales = {}
    for direccion in re.findall(r"Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2})", conectados):
        r = s.correr(["hcitool", "-i", cfg.bt_hci, "rssi", direccion], tope=5)
        hallado = re.search(r"RSSI return value:\s*(-?\d+)", r.salida) if r.ok else None
        if hallado:
            senales[direccion] = int(hallado.group(1))
    return senales


@resiste(valor(None))
def dispositivo_usb(s: Sistema, cfg: Config) -> str | None:
    """Nombre USB del adaptador (p. ej. 1-10): por el hci y, si desaparecio, por vendedor:producto."""
    ruta = s.leer_enlace(f"/sys/class/bluetooth/{cfg.bt_hci}/device")
    if ruta:
        return os.path.basename(ruta).split(":", 1)[0]
    vendedor, producto = cfg.bt_usb.split(":", 1)
    for nombre in s.listar(USB):
        if (s.leer(f"{USB}/{nombre}/idVendor") or "").strip() == vendedor and (
            s.leer(f"{USB}/{nombre}/idProduct") or ""
        ).strip() == producto:
            return nombre
    return None


def _volvio(s: Sistema, cfg: Config) -> bool:
    return esperar(s, lambda: responde(s, cfg) is True, 20, paso=2)


@resiste(valor(False))
def encender(s: Sistema, cfg: Config) -> bool:
    s.correr(["bluetoothctl", "power", "on"], tope=15)
    return _volvio(s, cfg)


@resiste(valor(False))
def rfkill(s: Sistema, cfg: Config) -> bool:
    s.correr(["rfkill", "block", "bluetooth"])
    s.dormir(2)
    s.correr(["rfkill", "unblock", "bluetooth"])
    return pausa(s, 2) and encender(s, cfg)


@resiste(valor(False))
def religar(s: Sistema, cfg: Config) -> bool:
    """Desliga y liga btusb en cada interfaz del adaptador: el driver vuelve a cargar el firmware."""
    disp = dispositivo_usb(s, cfg)
    if disp is None:
        return False
    interfaces = [n for n in s.listar(USB) if n.startswith(f"{disp}:")]
    for i in interfaces:
        s.escribir(f"{BTUSB}/unbind", i)
    s.dormir(2)
    for i in interfaces:
        s.escribir(f"{BTUSB}/bind", i)
    return pausa(s, 4) and encender(s, cfg)


@resiste(valor(False))
def autorizar(s: Sistema, cfg: Config) -> bool:
    disp = dispositivo_usb(s, cfg)
    if disp is None or not s.escribir(f"{USB}/{disp}/authorized", "0"):
        return False
    s.dormir(3)
    return s.escribir(f"{USB}/{disp}/authorized", "1") and pausa(s, 5) and encender(s, cfg)


@resiste(valor(False))
def usbreset(s: Sistema, cfg: Config) -> bool:
    return s.correr(["usbreset", cfg.bt_usb], tope=30).ok and pausa(s, 5) and encender(s, cfg)


@resiste(valor((False, None)))
def reparar(s: Sistema, cfg: Config) -> tuple[bool, str | None]:
    """Prueba la escalera; si algo funciono, arranca las unidades que reponen el NAP y la visibilidad."""
    pasos = [
        ("encender", lambda: encender(s, cfg)),
        ("rfkill", lambda: rfkill(s, cfg)),
        ("religar btusb", lambda: religar(s, cfg)),
    ]
    if cfg.bt_usb_profundo:
        pasos += [("authorized", lambda: autorizar(s, cfg)), ("usbreset", lambda: usbreset(s, cfg))]
    d = con_respaldo("reparar bluetooth", pasos)
    for unidad in cfg.bt_reponer if d.ok else ():
        intentos.latido()
        s.correr(["systemctl", "start", "--no-block", unidad], tope=15)
    return d.ok, d.paso
