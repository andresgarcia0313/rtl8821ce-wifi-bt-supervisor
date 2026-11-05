"""Eleccion de banda: 5 GHz primero; 2,4 GHz solo cuando lejos del router rinde mejor y pierde menos.

La casa emite un SSID por banda, asi que cambiar de banda es cambiar de perfil de NetworkManager. Umbrales
tomados de Android e iwd: 5 GHz pierde puntos por debajo de -75 dBm e iwd hace roaming a -76 dBm en 5 GHz.
Para no saltar de un lado a otro hay histeresis (se vuelve a 5 GHz solo con -67 dBm o mas) y tiempos de
permanencia. NetworkManager tambien prefiere 5 GHz por la prioridad de autoconexion de los perfiles.

En 2,4 GHz la wifi y el Bluetooth comparten la banda (y en este chip combo, la antena): con el comando HCI
estandar "Set AFH Host Channel Classification" el Bluetooth deja de saltar por los canales de la wifi.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from .config import Config
from .diagnostico import Estado
from .intentos import resiste, valor
from .perfiles import Perfiles
from .sistema import Sistema
from .sondas import Medida

log = logging.getLogger(__name__)
BAJA_5G = -75  # dBm: por debajo, 5 GHz pierde frente a 2,4 GHz (Android, iwd)
SUBE_5G = -67  # dBm: para volver a 5 GHz (8 dB de histeresis)
VENTAJA_2G = 6  # dB que 2,4 GHz debe ganarle a 5 GHz para que valga el cambio
SOSTENIDO = 60.0  # segundos de senal baja antes de cambiar
CADA_BUSQUEDA = 120.0  # en 2,4 GHz, cada cuanto mirar si 5 GHz volvio
PERMANENCIA = 300.0  # tras un cambio, minimo en la banda nueva
ANCHO_WIFI = 11  # MHz a cada lado del centro de un canal wifi de 20 MHz


def es_2g(frecuencia: int | None) -> bool:
    return frecuencia is not None and frecuencia < 3000


@resiste(valor(None))
def senal_en_escaneo(s: Sistema, cfg: Config, ssid: str) -> int | None:
    """Mejor senal (dBm) del SSID en los resultados que ya tiene el kernel; None si no aparece."""
    r = s.correr(["iw", "dev", cfg.iface, "scan", "dump"], tope=10)
    mejores = [
        int(float(m.group(1)))
        for bloque in r.salida.split("\nBSS ")
        if f"SSID: {ssid}\n" in bloque + "\n" and (m := re.search(r"signal:\s*(-?[\d.]+)", bloque))
    ]
    return max(mejores) if mejores else None


TODOS_LIBRES = ["ff"] * 9 + ["7f"]


@resiste(lambda *_a, **_k: list(TODOS_LIBRES))
def mapa_afh(frecuencia: int | None) -> list[str]:
    """10 bytes: un bit por canal Bluetooth (2402 + k MHz, k = 0..78); 0 = ocupado por la wifi."""
    bits = [
        0 if es_2g(frecuencia) and abs(2402 + k - (frecuencia or 0)) <= ANCHO_WIFI else 1 for k in range(79)
    ]
    bits.append(0)  # bit 79 reservado
    return [f"{sum(bits[i * 8 + j] << j for j in range(8)):02x}" for i in range(10)]


@resiste(valor(False))
def avisar_canal_al_bluetooth(s: Sistema, cfg: Config, frecuencia: int | None) -> bool:
    orden = ["hcitool", "-i", cfg.bt_hci, "cmd", "0x03", "0x003F", *mapa_afh(frecuencia)]
    r = s.correr(orden, tope=10)
    return r.ok and "3F 0C 00" in r.salida.upper()  # evento de comando completado con estado 0


class Banda:
    def __init__(
        self,
        s: Sistema,
        cfg: Config,
        anotar: Callable[..., object] = lambda *a, **k: None,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.s, self.cfg, self.anotar, self.reloj = s, cfg, anotar, reloj
        self.p = Perfiles(s, cfg)
        self.baja_desde: float | None = None
        self.ultimo_cambio = self.ultima_busqueda = -1e9
        self.frecuencia_afh: int | None = -1  # la ultima enviada al Bluetooth (-1: ninguna aun)

    @resiste(valor(None))
    def vigilar(self, estado: Estado, m: Medida) -> None:
        if not self.cfg.conexion_2g or self.cfg.modo == "observar":
            return
        self.convivencia(m.frecuencia)
        if estado is not Estado.SANO and not m.asociado:
            return  # sin enlace decide la escalera de remedios (levantar prueba las dos bandas)
        if self.reloj() - self.ultimo_cambio < PERMANENCIA:
            return
        if es_2g(m.frecuencia):
            self.volver_a_5g()
        else:
            self.bajar_a_2g(m.senal)

    @resiste(valor(None))
    def convivencia(self, frecuencia: int | None) -> None:
        """Avisa al Bluetooth el canal de la wifi cuando cambia (en 5 GHz, todos los canales libres)."""
        clave = frecuencia if es_2g(frecuencia) else None
        cambio = clave != self.frecuencia_afh and self.cfg.bluetooth
        if cambio and avisar_canal_al_bluetooth(self.s, self.cfg, clave):
            self.frecuencia_afh = clave

    @resiste(valor(False))
    def bajar_a_2g(self, senal: int | None) -> bool:
        if senal is None or senal >= BAJA_5G:
            self.baja_desde = None
            return False
        self.baja_desde = self.reloj() if self.baja_desde is None else self.baja_desde
        if self.reloj() - self.baja_desde < SOSTENIDO:
            return False
        ssid_2g = self.p.nm("-g", "802-11-wireless.ssid", "connection", "show", self.cfg.conexion_2g)
        otra = senal_en_escaneo(self.s, self.cfg, ssid_2g) if ssid_2g else None
        if otra is None or otra - senal < VENTAJA_2G:
            return False  # 2,4 GHz no se ve o no gana lo suficiente: se queda en 5 GHz
        return self.cambiar(self.cfg.conexion_2g, f"5 GHz a {senal} dBm, 2,4 GHz a {otra} dBm")

    @resiste(valor(False))
    def volver_a_5g(self) -> bool:
        if self.reloj() - self.ultima_busqueda < CADA_BUSQUEDA:
            return False
        self.ultima_busqueda = self.reloj()
        ssid = self.p.nm("-g", "802-11-wireless.ssid", "connection", "show", self.cfg.conexion)
        self.p.visible(ssid or "")  # pide un escaneo fresco (una vez cada CADA_BUSQUEDA)
        senal = senal_en_escaneo(self.s, self.cfg, ssid) if ssid else None
        if senal is None or senal < SUBE_5G:
            return False
        return self.cambiar(self.cfg.conexion, f"5 GHz de vuelta a {senal} dBm")

    @resiste(valor(False))
    def cambiar(self, perfil: str, motivo: str) -> bool:
        self.ultimo_cambio, self.baja_desde = self.reloj(), None
        ok = self.p.subir(perfil, 40)
        if not ok:  # la banda nueva no levanto: de vuelta a la otra
            otro = self.cfg.conexion if perfil == self.cfg.conexion_2g else self.cfg.conexion_2g
            self.p.subir(otro, 40)
        log.info("banda: %s -> perfil %s (%s)", motivo, perfil, ok)
        self.anotar("banda", perfil=perfil, motivo=motivo, ok=ok)
        return ok
