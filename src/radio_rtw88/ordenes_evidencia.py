"""Que registros guarda la evidencia de una falla, archivo por archivo (una lista de ordenes cada uno)."""

from __future__ import annotations

from .config import Config

DESDE = "-15min"  # ventana de los registros del journal alrededor de la falla
J = ["journalctl", "--no-pager", "-o", "short-iso-precise", "--since", DESDE]
PARAMETROS = (
    'for p in /sys/module/rtw88*/parameters/* /sys/module/btusb/parameters/*; do echo "$p=$(cat $p)"; done'
)
# Un nodo de k3s registra miles de avisos de AppArmor de los contenedores de k3s: se filtran para que
# no empujen fuera del recorte las lineas de la radio; aparte va un registro solo de wifi/BT/PCI.
RUIDO = "apparmor=|UFW "  # avisos de AppArmor de los contenedores y auditoria del cortafuegos
SIN_RUIDO = " ".join(J) + f" -k | grep -vE '{RUIDO}' | tail -n 4000"
FILTRO_RADIO = "rtw|wlo|mac80211|cfg80211|wlan|bluetooth|btusb|btrtl|hci0|pcieport|AER|usb 1-"
RADIO = " ".join(J) + f" -k | grep -vE '{RUIDO}' | grep -iE '{FILTRO_RADIO}'"
PRESION = ["cat", "/proc/pressure/cpu", "/proc/pressure/memory", "/proc/pressure/io"]


def registros() -> dict[str, list[list[str]]]:
    """Lo que guarda el journal: no se pierde, asi que se toma despues del remedio (no lo retrasa)."""
    return {
        "kernel.txt": [["sh", "-c", SIN_RUIDO]],
        "kernel-radio.txt": [["sh", "-c", RADIO]],
        "red.txt": [[*J, "-u", "NetworkManager", "-u", "wpa_supplicant"]],
        "bluetooth-journal.txt": [[*J, "-u", "bluetooth"]],
        "controlador.txt": [[*J, "-u", "controlador-radio"]],
    }


def volatil(cfg: Config) -> dict[str, list[list[str]]]:
    """Lo que cambia o se pierde al reparar: se toma antes de tocar nada (unos segundos)."""
    i = cfg.iface
    return {
        "red-estado.txt": [["ip", "-s", "addr"], ["ip", "route"], ["nmcli", "-t", "device"]],
        "wifi.txt": [
            ["iw", "dev", i, "link"],
            ["iw", "dev", i, "station", "dump"],
            ["iw", "dev", i, "info"],
            ["nmcli", "-f", "all", "device", "show", i],
            ["iw", "dev", i, "scan", "dump"],
        ],
        "bluetooth.txt": [
            ["bluetoothctl", "show"],
            ["hciconfig", "-a"],
            ["hcitool", "-i", cfg.bt_hci, "cmd", "0x04", "0x0001"],
            ["bluetoothctl", "devices", "Connected"],
            ["sh", "-c", "lsusb -t; dmesg | grep -iE 'usb 1-|bluetooth' | tail -n 40"],
        ],
        "pci.txt": [["lspci", "-vvv", "-s", cfg.pci.split(":", 1)[1]]],  # errores AER y enlace PCIe
        "chip.txt": [  # estado del chip y de la coexistencia wifi/Bluetooth que hace el driver
            [
                "sh",
                "-c",
                f"d=/sys/kernel/debug/ieee80211/$(cat /sys/class/net/{i}/phy80211/name)/rtw88; "
                'for f in phy_info coex_info mac_0; do echo "== $f"; timeout -s KILL 10 cat "$d/$f"; done',
            ],
            ["sh", "-c", PARAMETROS],
        ],
        "sistema.txt": [
            ["uptime"],
            ["free", "-m"],
            PRESION,
            ["sensors"],
            ["rfkill"],
            ["top", "-bn1", "-w", "200"],
        ],
    }
