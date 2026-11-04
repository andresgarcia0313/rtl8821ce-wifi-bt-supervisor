"""controlador-radio <orden>

demonio            bucle de vigilancia (lo usa systemd)
diagnostico        mide cada capa y dice la causa, sin tocar nada
avisar-caida       aviso critico de que systemd dejo de reiniciar el demonio (OnFailure)
ajustes            opciones del driver al estilo Windows y su valor actual
estado             contadores acumulados, ultima medida y estado del Bluetooth
eventos [n]        ultimos n eventos de la bitacora (por que fallo, en que escenario, evidencia)
evidencia          guarda ahora los registros completos de wifi y Bluetooth (para revisar a mano)
reparar            una vuelta completa: diagnostica y aplica el remedio si hace falta
bt estado|reparar  el Bluetooth responde a un comando HCI? / aplica la escalera de reparacion
probar <remedio>   aplica un remedio a proposito y mide cuanto tarda en volver
                   wifi: reasociar | reiniciar-firmware | recargar-modulo | reset-pci
                   bt:   bt-encender | bt-rfkill | bt-religar | bt-authorized | bt-usbreset
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import asdict, replace

from . import acciones, ajustes, bluetooth, cerrojo, demonio, evidencia, principal, servicio, sondas
from .config import cargar
from .diagnostico import diagnosticar
from .eventos import Bitacora
from .registro import Registro
from .sistema import SistemaReal

REMEDIOS = {
    "reasociar": acciones.reasociar,
    "reiniciar-firmware": acciones.reiniciar_firmware,
    "recargar-modulo": acciones.recargar_modulo,
    "reset-pci": acciones.reset_pci,
    "bt-encender": bluetooth.encender,
    "bt-rfkill": bluetooth.rfkill,
    "bt-religar": bluetooth.religar,
    "bt-authorized": bluetooth.autorizar,
    "bt-usbreset": bluetooth.usbreset,
}


def _imprimir(datos: object) -> None:
    print(json.dumps(datos, indent=1, ensure_ascii=False, sort_keys=True))


def main(args: list[str]) -> int:
    os.umask(0o077)  # bitacora y evidencia tienen datos de la red: solo root las lee
    s, cfg = SistemaReal(), cargar()
    orden = args[0] if args else ""
    if orden == "demonio":
        return demonio.main(s, cfg)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if orden == "diagnostico":
        m = sondas.medir(s, cfg)
        _imprimir(asdict(m) | {"causa": str(diagnosticar(m))})
        return 0
    if orden == "avisar-caida":
        servicio.configurar(cfg.nombre, cfg.aviso_env)
        servicio.avisar(
            "critical", "systemd dejo de reiniciar el controlador de radio; siguen los de reserva"
        )
        return 0
    if orden == "ajustes":
        _imprimir(ajustes.leer_todos(s, cfg))
        return 0
    if orden == "estado":
        _imprimir(Registro(cfg.estado_dir).datos | {"bluetooth_responde": bluetooth.responde(s, cfg)})
        return 0
    if orden == "eventos":
        n = int(args[1]) if len(args) == 2 and args[1].isdigit() else 20
        for e in Bitacora(cfg.estado_dir).ultimos(n):
            print(json.dumps(e, ensure_ascii=False))
        return 0
    if orden == "evidencia":
        print(evidencia.capturar(s, cfg, "manual") or "no se pudo guardar la evidencia")
        return 0
    if orden == "reparar":
        c = principal.Controlador(s, replace(cfg, confirmar=1))  # orden explicita: actua en esta vuelta
        return 0 if c.vuelta() == "sano" else 1
    if orden == "bt" and len(args) == 2 and args[1] in ("estado", "reparar"):
        if args[1] == "estado":
            _imprimir({"responde": bluetooth.responde(s, cfg), "usb": bluetooth.dispositivo_usb(s, cfg)})
            return 0
        with cerrojo.exclusivo(esperar=True):
            ok, paso = bluetooth.reparar(s, cfg)
        _imprimir({"reparado": ok, "paso": paso})
        return 0 if ok else 1
    remedio = REMEDIOS.get(args[1]) if len(args) == 2 else None
    if orden == "probar" and remedio is not None:
        with cerrojo.exclusivo(esperar=True):
            t0 = time.monotonic()
            ok = remedio(s, cfg)
        _imprimir({"remedio": args[1], "recupero": ok, "segundos": round(time.monotonic() - t0, 1)})
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
