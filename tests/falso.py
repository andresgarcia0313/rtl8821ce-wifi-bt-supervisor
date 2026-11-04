"""Sistema falso para las pruebas: responde segun reglas y registra cada orden y escritura."""

from __future__ import annotations

from collections.abc import Callable

from radio_rtw88.config import Config
from radio_rtw88.sistema import Resultado

C = Config()
LINK_OK = (
    f"Connected to 02:00:00:00:00:01 (on {C.iface})\n\tfreq: 5745.0\n\tsignal: -33 dBm\n"
    "\ttx bitrate: 433.3 MBit/s VHT-MCS 9 80MHz"
)
DEBUGFS = "/sys/kernel/debug/ieee80211/phy0/rtw88"
MAC_VIVO = "00000000  dddfbe80    00030012    00207c23    00000000\n"
MAC_MUERTO = "00000000  ffffffff    ffffffff    ffffffff    ffffffff\n"
HCI_OK = "< HCI Command: ogf 0x04, ocf 0x0001, plen 0\n> HCI Event: 0x0e plen 12\n"


class SistemaFalso:
    def __init__(self) -> None:
        self.ordenes: list[list[str]] = []
        self.escrituras: list[tuple[str, str]] = []
        self.archivos: dict[str, str] = {
            f"/sys/class/net/{C.iface}/operstate": "up",
            f"/sys/class/net/{C.iface}/phy80211/name": "phy0\n",
            f"/sys/bus/pci/devices/{C.pci}/vendor": "0x10ec",
        }
        self.enlaces = {f"/sys/class/bluetooth/{C.bt_hci}/device": "/sys/devices/pci0/usb1/1-10/1-10:1.0"}
        self.carpetas = {"/sys/bus/usb/devices": ["1-0:1.0", "1-10", "1-10:1.0", "1-10:1.1", "usb1"]}
        self.asociado = self.puerta = self.internet = self.firmware = True
        self.ssid_visible = True
        self.bt_vivo = True  # el Bluetooth contesta comandos HCI
        self.otras_redes: list[str] = []  # SSID visibles ademas de la casa
        self.activa = "wifi-casa"  # perfil wifi activo
        self.bt = False  # perfil bt-celular activo
        self.no_suben: set[str] = set()  # perfiles cuyo 'connection up' falla
        self.al_escribir: dict[str, Callable[[], bool]] = {}  # ruta -> efecto (devuelve exito)
        self.al_correr: dict[str, Callable[[list[str]], Resultado]] = {}  # primera palabra -> efecto

    def correr(self, orden: list[str], tope: float = 20) -> Resultado:
        self.ordenes.append(orden)
        if orden[0] in self.al_correr:
            return self.al_correr[orden[0]](orden)
        if orden[0] in ("ping", "arping"):  # arping solo se usa con la puerta de enlace
            ok = self.puerta if orden[-1] == C.puerta else self.internet
            return Resultado(0 if ok and self.asociado else 1)
        if orden[0] == "hcitool":
            return Resultado(0, HCI_OK) if self.bt_vivo else Resultado(1, error="timeout")
        if orden[:2] == ["bluetoothctl", "show"]:
            return Resultado(0, f"\tPowered: {'yes' if self.bt_vivo else 'no'}\n")
        if orden[:5] == ["iw", "dev", C.iface, "station", "dump"]:
            return Resultado(
                0, "\ttx retries:\t3\n\ttx failed:\t1\n\tbeacon loss:\t34\n\tsignal avg:\t-36 [-36] dBm\n"
            )
        if orden[:3] == ["iw", "dev", C.iface] and orden[3] == "link":
            return Resultado(0, LINK_OK if self.asociado else "Not connected.")
        if orden[:2] == ["nmcli", "-t"]:
            casa = "wifi-casa\n" if self.ssid_visible else "otra\n"
            return Resultado(0, casa + "".join(f"{r}\n" for r in self.otras_redes))
        if orden[:3] == ["nmcli", "connection", "up"] or orden[:3] == ["nmcli", "connection", "down"]:
            return self._perfil(orden[2] == "up", orden[3])
        if orden[:3] == ["nmcli", "-g", "GENERAL.CONNECTION"]:
            return Resultado(0, f"{self.activa}\n")
        if orden[:3] == ["nmcli", "-g", "GENERAL.STATE"]:
            return Resultado(0, "activated\n" if self.bt else "")
        if orden[:3] == ["nmcli", "-g", "bluetooth.bdaddr"]:
            return Resultado(0, "00\\:11\\:22\\:33\\:44\\:55\n")
        if orden[:2] == ["nmcli", "-g"]:
            return Resultado(0, "wifi-casa\n")
        return Resultado(0)

    def _perfil(self, subir: bool, nombre: str) -> Resultado:
        if nombre in self.no_suben:
            return Resultado(4)
        if nombre == "bt-celular":
            self.bt = subir
        elif subir:
            self.activa = nombre
        return Resultado(0)

    def escribir(self, ruta: str, texto: str) -> bool:
        self.escrituras.append((ruta, texto))
        efecto = self.al_escribir.get(ruta)
        return efecto() if efecto else True

    def leer(self, ruta: str) -> str | None:
        if ruta == f"{DEBUGFS}/mac_0":  # registros por MMIO: un chip fuera del bus devuelve todo en 1
            return MAC_VIVO if self.firmware else MAC_MUERTO
        return self.archivos.get(ruta)

    def leer_enlace(self, ruta: str) -> str | None:
        return self.enlaces.get(ruta)

    def listar(self, carpeta: str) -> list[str]:
        return self.carpetas.get(carpeta, [])

    def dormir(self, segundos: float) -> None:
        return None

    def ordeno(self, *palabras: str) -> bool:
        return any(o[: len(palabras)] == list(palabras) for o in self.ordenes)
