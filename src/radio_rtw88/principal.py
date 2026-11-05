"""Controlador: una vuelta mide, diagnostica, repara y anota; el bucle que la repite vive en demonio.py."""

from __future__ import annotations

import logging
import re
import threading
import time

from . import servicio, sondas
from .acciones import reasociar
from .ajustes import Ajustes
from .banda import Banda
from .config import Config
from .diagnostico import SIN_TOCAR_HARDWARE, Estado, diagnosticar
from .energia import Energia
from .episodios import Episodios
from .escucha_red import EscuchaRed
from .intentos import seguro
from .itinerancia import Itinerancia
from .kmsg import Escucha
from .politica import Politica
from .red import red_ok
from .registro import Registro
from .respaldo import Respaldo
from .sistema import Sistema
from .vigia_bt import VigiaBt
from .vigia_cable import VigiaCable

log = logging.getLogger(__name__)
VENTANA_CRASH = 120  # segundos durante los que un crash del kernel cuenta para el diagnostico
PRESION_ALTA = 50.0  # % de tiempo con tareas esperando CPU (PSI, ultimos 10 s)
ALERTA = 120  # segundos de ritmo corto tras un evento de la wifi
CADA_RESUMEN = 600  # segundos entre intentos de enviar el resumen diario (solo sale una vez al dia)


class Controlador:
    def __init__(self, s: Sistema, cfg: Config) -> None:
        self.s, self.cfg = s, cfg
        self.registro = Registro(cfg.estado_dir)
        usos = self.registro.datos.setdefault("hw", [])
        self.politica = Politica(s, cfg, usos=usos, al_usar=self.registro.guardar)
        self.episodios = Episodios(s, cfg)
        self.escucha = Escucha(self.al_kernel)
        self.vigia_bt = VigiaBt(s, cfg, self.episodios, self.escucha.silenciar_bt)
        self.respaldo = Respaldo(s, cfg, lambda tipo, **d: self.episodios.bitacora.anotar("red", tipo, **d))
        self.vigia_cable = VigiaCable(s, lambda tipo, **d: self.episodios.bitacora.anotar("red", tipo, **d))
        self.ajustes = Ajustes(s, cfg, lambda tipo, **d: self.episodios.bitacora.anotar("radio", tipo, **d))
        self.itinerancia = Itinerancia(
            s, cfg, lambda tipo, **d: self.episodios.bitacora.anotar("wifi", tipo, **d)
        )
        self.banda = Banda(s, cfg, lambda tipo, **d: self.episodios.bitacora.anotar("wifi", tipo, **d))
        self.energia = Energia(s, cfg, lambda tipo, **d: self.episodios.bitacora.anotar("radio", tipo, **d))
        self.escucha_red = EscuchaRed(cfg, self.al_red)
        self.despertar = threading.Event()
        self.alerta_hasta = -1e9  # tras un evento de la wifi se revisa al ritmo corto un rato
        self.ultimo_crash = self.ultimo_resumen = -1e9
        self.fallas = 0
        self.desde_falla = 0.0  # inicio de la falla actual (tiempo de recuperacion)

    def al_kernel(self, equipo: str, linea: str) -> None:
        """Desde el hilo de la escucha: anota y despierta al bucle, que captura la evidencia."""
        log.warning("error del kernel (%s) en vivo: %s", equipo, linea)
        if equipo == "wifi":
            self.registro.crash()
            self.ultimo_crash = time.monotonic()
        else:
            self.vigia_bt.revisar_ya()
        self.episodios.kernel(equipo, linea)
        self.despertar.set()  # revisar ya, sin esperar el intervalo

    def al_red(self, tipo: str, linea: str) -> None:
        """Desde el hilo de nl80211: una falla de la wifi despierta al bucle en el mismo segundo."""
        if tipo == "falla":
            log.warning("evento de la wifi en vivo: %s", linea)
            self.alerta_hasta = time.monotonic() + ALERTA
            self.despertar.set()

    def confirmar(self) -> int:
        """Con la CPU muy presionada una sonda puede vencer sin falla de la wifi: dos confirmaciones mas."""
        crudo = self.s.leer("/proc/pressure/cpu") or ""
        presion = re.search(r"some avg10=([\d.]+)", crudo)
        return self.cfg.confirmar + (2 if presion and float(presion.group(1)) >= PRESION_ALTA else 0)

    def al_despertar(self) -> None:
        """El equipo salio de suspension: revisar wifi y Bluetooth ya, al ritmo corto un rato."""
        log.info("el equipo desperto de una suspension: reviso ya")
        self.alerta_hasta = time.monotonic() + ALERTA
        self.vigia_bt.revisar_ya()
        self.despertar.set()

    def intervalo(self) -> float:
        """Ritmo corto con sospecha, falla o evento reciente; largo con todo sano (menos CPU y energia)."""
        alerta = self.fallas > 0 or time.monotonic() < self.alerta_hasta or self.vigia_bt.sospecha
        return self.cfg.intervalo if alerta else max(self.cfg.intervalo, self.cfg.intervalo_estable)

    def _sano(self) -> None:
        if self.fallas:
            log.info("wifi sana otra vez tras %d revisiones con falla", self.fallas)
            self.episodios.recuperada_sola(self.fallas, time.monotonic() - self.desde_falla)
        self.fallas = 0
        if time.monotonic() - self.ultimo_resumen > CADA_RESUMEN:
            self.ultimo_resumen = time.monotonic()
            servicio.avisar("resumen", "")

    def vuelta(self) -> Estado:
        self.episodios.atender_kernel()
        m = sondas.medir(self.s, self.cfg)
        crash = time.monotonic() - self.ultimo_crash < VENTANA_CRASH
        estado = diagnosticar(m, crash)
        estado = seguro("respaldo: ajustar", lambda: self.respaldo.ajustar(estado), lambda: estado)
        self.registro.causa(estado, m)
        self.itinerancia.vigilar(estado)  # fija el punto de acceso sano o lo suelta si dejo de verse
        self.banda.vigilar(estado, m)  # 5 GHz primero; 2,4 GHz si lejos rinde mejor
        if estado is Estado.SANO:
            self._sano()
            self._respaldo(estado)
            return estado
        self.fallas += 1
        self._respaldo(estado)  # el internet de respaldo sube antes de los remedios
        log.warning("causa: %s (revision %d) %s", estado, self.fallas, m)
        if self.fallas == 1:  # episodio nuevo: evidencia antes de tocar nada
            self.desde_falla = time.monotonic()
            self.episodios.falla(estado, m, self.registro.crashes_desde(86400))
        urgente = estado is Estado.SIN_INTERFAZ or (estado is Estado.FIRMWARE and crash)
        if self.fallas < self.confirmar() and not urgente:
            return estado  # histeresis: confirmar antes de actuar
        self.escucha.silenciar(180)  # los remedios provocan mensajes de crash: no son nuevos
        desenlace = self.politica.actuar(estado)
        if desenlace is None or self.cfg.modo == "observar":
            return estado
        self.registro.remedio(desenlace.paso)
        segundos = time.monotonic() - self.desde_falla
        self.episodios.remedio(estado, desenlace, segundos)
        if desenlace.ok:
            log.info("recuperada de '%s' con '%s' en %.0f s", estado, desenlace.paso, segundos)
            self.registro.recuperacion(segundos)
            servicio.avisar("recovered", f"'{estado}' resuelta con '{desenlace.paso}' en {segundos:.0f} s")
            self.fallas = 0
            self.episodios.carpeta = None
        elif estado not in SIN_TOCAR_HARDWARE:
            servicio.avisar("critical", f"no se recupera de '{estado}' (intentado: {desenlace.fallidos})")
        return estado

    def _respaldo(self, estado: Estado) -> None:
        seguro("respaldo de internet", lambda: self.respaldo.atender(estado, self.fallas), lambda: None)

    def vigilar_bt(self) -> None:
        """Bluetooth y cable: su falla nunca cuenta como vuelta fallida (no dispara el respaldo de wifi)."""
        seguro("vigia del bluetooth", self.vigia_bt.vigilar, lambda: None)
        seguro("vigia del cable", self.vigia_cable.vigilar, lambda: None)
        seguro("ajustes del driver", self.ajustes.vigilar, list)
        seguro("energia", self.energia.vigilar, lambda: None)

    def respaldo_minimo(self) -> str:
        """El except de una vuelta: si la wifi no cursa trafico, reasociar sin mas analisis."""
        if self.cfg.modo == "observar" or red_ok(self.s, self.cfg):
            return "error interno, wifi con trafico"
        return "error interno, reasociada" if reasociar(self.s, self.cfg) else "error interno, sin red"
