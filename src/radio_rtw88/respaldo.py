"""Respaldo de internet por el celular: su cable USB, su wifi y su Bluetooth.

- Cable USB con internet: es el respaldo y lo maneja el ruteo (metrica 700 contra 600 de la wifi, y la
  verificacion de conectividad de NetworkManager penaliza la wifi sin internet). Con el cable util no se
  mueve la wifi ni se sube el Bluetooth: la wifi sigue en la red local.

- Red local sin internet: solo el Bluetooth; mover la wifi sacaria al equipo de la red local.
- Router ausente: Bluetooth ya (la wifi vuelve sola si el router solo se reinicio) y, pasados
  espera_celular segundos, la wifi del celular. Desde ella busca la casa cada volver_casa segundos.
- Wifi con internet soltar_bt segundos seguidos: suelta el Bluetooth. La ruta la elige NetworkManager
  (la verificacion de conectividad penaliza la wifi sin internet). Perfil wifi = SSID.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .config import Config
from .diagnostico import Estado
from .intentos import con_respaldo
from .perfiles import Perfiles
from .sistema import Sistema

REINTENTO_BT = 120.0  # segundos entre intentos de subir el Bluetooth si no conecto


class Respaldo:
    def __init__(
        self,
        s: Sistema,
        cfg: Config,
        anotar: Callable[..., object] = lambda *a, **k: None,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.s, self.cfg, self.anotar, self.reloj = s, cfg, anotar, reloj
        self.p = Perfiles(s, cfg)
        self.sano_desde: float | None = None
        self.ausente_desde: float | None = None
        self.ultimo_bt = self.ultimo_cambio = -1e9

    def ajustar(self, estado: Estado) -> Estado:
        """En la wifi del celular la puerta de la casa no existe: sin internet es el celular, no el radio."""
        return Estado.PROVEEDOR if estado is not Estado.SANO and self.p.en_celular() else estado

    def subir_bt(self) -> None:
        if not self.cfg.bt_celular:
            return
        if self.reloj() - self.ultimo_bt < REINTENTO_BT or self.p.bt_activo():
            return
        self.ultimo_bt = self.reloj()
        mac = self.p.mac_bt()
        pasos = [
            ("nmcli con up", lambda: self.p.subir(self.cfg.bt_celular, 50)),
            (
                "bluetoothctl connect",
                lambda: (
                    self.s.correr(["bluetoothctl", "connect", mac], tope=20).ok
                    and self.p.subir(self.cfg.bt_celular, 50)
                ),
            ),
        ]
        d = con_respaldo("internet por el Bluetooth del celular", pasos)
        self.anotar("respaldo", accion="sube bluetooth", ok=d.ok, paso=d.paso, fallidos=list(d.fallidos))

    def soltar_bt(self) -> None:
        if self.cfg.bt_celular and self.p.bt_activo():
            ok = self.p.bajar(self.cfg.bt_celular)
            self.anotar("respaldo", accion="suelta bluetooth", ok=ok)

    def _cambiar(self, desde_celular: bool) -> None:
        """Pasa la wifi a la casa o al celular si el destino se ve; como mucho una vez cada volver_casa."""
        if self.reloj() - self.ultimo_cambio < self.cfg.volver_casa:
            return
        self.ultimo_cambio = self.reloj()
        destino = self.cfg.conexion if desde_celular else self.cfg.celular
        if not self.p.visible(destino):
            return
        ok = self.p.subir(destino)
        if desde_celular and not ok:
            self.p.subir(self.cfg.celular)  # la casa no levanto: de vuelta al celular
        self.anotar("respaldo", accion=f"wifi a {destino}", ok=ok)

    def atender(self, estado: Estado, fallas: int) -> None:
        """Se llama en cada vuelta con el diagnostico ya ajustado; cada orden lleva su tope."""
        if self.cfg.modo == "observar" or not self.cfg.respaldo:
            return  # sin respaldo propio: ajustar() sigue evitando remedios de hardware en el celular
        ahora = self.reloj()
        if estado is Estado.SANO:
            self.ausente_desde = None
            self.sano_desde = ahora if self.sano_desde is None else self.sano_desde
            if ahora - self.sano_desde >= self.cfg.soltar_bt:
                self.soltar_bt()
            if self.p.en_celular():
                self._cambiar(desde_celular=True)
            return
        self.sano_desde = None
        if fallas < self.cfg.confirmar:
            return
        if self.p.cable_util():
            self.ausente_desde = None
            if self.p.en_celular():
                self._cambiar(desde_celular=True)
            return
        self.subir_bt()
        if self.p.en_celular():
            self._cambiar(desde_celular=True)  # el celular tampoco tiene internet: probar la casa
        elif estado is Estado.AP_AUSENTE:
            self.ausente_desde = ahora if self.ausente_desde is None else self.ausente_desde
            if ahora - self.ausente_desde >= self.cfg.espera_celular:
                self._cambiar(desde_celular=False)
