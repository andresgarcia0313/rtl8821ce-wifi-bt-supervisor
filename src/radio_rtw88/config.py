"""Configuracion: valores por defecto sobrescribibles en /etc/controlador-radio/config.toml."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

log = logging.getLogger(__name__)
RUTA = "/etc/controlador-radio/config.toml"


@dataclass(frozen=True)
class Config:
    modo: str = "actuar"  # "observar": diagnostica y registra sin tocar nada (para estrenar cambios)
    nombre: str = "servidor"  # como aparece el equipo en los avisos
    aviso_env: str = ""  # archivo con las variables del modulo de avisos (vacio: ninguno)
    iface: str = "wlo1"
    conexion: str = "wifi-casa"
    pci: str = "0000:02:00.0"
    modulo: str = "rtw88_8821ce"  # el modulo del chip; modprobe -r baja tambien rtw88_pci y rtw88_core
    puerta: str = "192.0.2.1"  # tu puerta de enlace (valor de documentacion)
    internet: tuple[str, ...] = ("1.1.1.1", "8.8.8.8", "9.9.9.9")
    intervalo: float = 15.0  # segundos entre revisiones normales
    confirmar: int = 2  # revisiones fallidas seguidas antes de actuar (salvo crash de firmware)
    max_resets_hora: int = 4  # tope de acciones sobre el hardware por hora (evita tormentas)
    espera_ap: float = 60.0  # con el punto de acceso ausente, cada cuanto reintentar asociar
    espera_router: float = 600.0  # tras una falla del proveedor, segundos en que solo se reasocia
    respaldo: bool = True  # False: la escalera de red la lleva otro servicio y aqui solo se repara el radio
    celular: str = "wifi-celular"  # perfil (y SSID) de la wifi que comparte el celular
    bt_celular: str = ""  # perfil del internet por el Bluetooth del celular (vacio: sin ese paso)
    espera_celular: float = 180.0  # router ausente: segundos antes de pasar la wifi al celular
    volver_casa: float = 120.0  # en el celular: cada cuanto buscar la casa para volver
    soltar_bt: float = 300.0  # wifi con internet: segundos antes de soltar el Bluetooth
    estado_dir: str = "/var/lib/controlador-radio"
    bluetooth: bool = True  # vigilar el Bluetooth y repararlo si deja de responder
    bt_hci: str = "hci0"
    bt_usb: str = "0bda:b00a"  # vendedor:producto, para hallarlo en USB si el hci desaparece
    bt_usb_profundo: bool = False  # authorized=0/1 y usbreset: solo tras probar que el equipo vuelve
    bt_reponer: tuple[str, ...] = ()  # unidades a arrancar tras reparar el Bluetooth (NAP, visibilidad)
    ajustes: bool = True  # vigilar ahorro de energia de la wifi y suspension USB del Bluetooth


# Limites sanos: fuera de ellos el valor se ignora (p. ej. un intervalo >= WatchdogSec mataria al demonio)
RANGOS: dict[str, tuple[float, float]] = {
    "intervalo": (5, 120),
    "confirmar": (1, 10),
    "max_resets_hora": (0, 20),
    "espera_ap": (10, 3600),
    "espera_router": (60, 3600),
    "espera_celular": (30, 3600),
    "volver_casa": (60, 3600),
    "soltar_bt": (30, 3600),
}
MODOS = ("actuar", "observar")


def _valido(clave: str, valor: object) -> bool:
    if clave == "modo":
        return valor in MODOS
    minimo, maximo = RANGOS.get(clave, (float("-inf"), float("inf")))
    return not isinstance(valor, int | float) or minimo <= valor <= maximo


def cargar(ruta: str = RUTA) -> Config:
    """Lee el TOML; si falta o esta mal, sigue con los valores por defecto (nunca detiene el demonio)."""
    base = Config()
    try:
        datos = tomllib.loads(Path(ruta).read_text())
    except FileNotFoundError:
        return base
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.error("config %s ilegible (%s): uso los valores por defecto", ruta, exc)
        return base
    validos = {f.name for f in fields(Config)}
    cambios: dict[str, object] = {}
    for clave, crudo in datos.items():
        valor = crudo
        if clave not in validos:
            log.warning("config: clave desconocida '%s' ignorada", clave)
            continue
        actual = getattr(base, clave)
        if isinstance(actual, tuple) and isinstance(valor, list):
            valor = tuple(str(v) for v in valor)
        elif isinstance(actual, float) and isinstance(valor, int):
            valor = float(valor)
        if type(valor) is not type(actual) or not _valido(clave, valor):
            log.warning("config: '%s' = %r fuera de tipo o de rango, ignorado", clave, valor)
            continue
        cambios[clave] = valor
    return replace(base, **cambios)  # type: ignore[arg-type]
