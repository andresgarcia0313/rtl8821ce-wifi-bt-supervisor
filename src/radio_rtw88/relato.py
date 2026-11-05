"""Relato: cada evento de la bitacora contado en una frase sencilla, para corregir defectos y mejorar.

La bitacora sigue siendo JSON (para analizarla con herramientas); el campo "texto" y el comando
`controlador-radio bitacora` la vuelven legible para cualquier persona.
"""

from __future__ import annotations

from typing import Any

from .intentos import resiste

CAUSAS = {
    "sin_interfaz": "la tarjeta desaparecio del sistema",
    "firmware": "el chip dejo de responder",
    "zombi": "conectada pero sin trafico (cuelgue silencioso)",
    "desasociado": "se desconecto del router, que sigue visible",
    "ap_ausente": "no se ve el router",
    "proveedor": "el router responde pero internet no",
    "apagada": "la radio esta apagada a proposito",
}
EQUIPOS = {"wifi": "Wifi", "bt": "Bluetooth", "radio": "Radio", "red": "Red"}


def _ok(e: dict[str, Any]) -> str:
    return "bien" if e.get("ok", e.get("corregido")) else "sin exito"


def _causa(e: dict[str, Any]) -> str:
    return CAUSAS.get(str(e.get("causa")), str(e.get("causa")))


FRASES: dict[str, Any] = {
    "falla": lambda e: f"falla: {_causa(e)}",
    "remedio": lambda e: (
        f"reparada con '{e.get('paso')}' en {e.get('segundos')} s ({_causa(e)})"
        if e.get("ok")
        else f"ningun remedio la reparo ({_causa(e)}); probados: {', '.join(e.get('fallidos') or [])}"
    ),
    "recuperada_sola": lambda e: f"se recupero sola en {e.get('segundos')} s, sin tocar nada",
    "error_kernel": lambda e: f"el kernel reporto un error: {str(e.get('detalle'))[-120:]}",
    "ajuste": lambda e: f"ajuste '{e.get('ajuste')}' desviado; corregido: {_ok(e)}",
    "itinerancia": lambda e: f"punto de acceso {e.get('bssid')}: {e.get('accion')} ({_ok(e)})",
    "banda": lambda e: f"cambio de banda a {e.get('perfil')}: {e.get('motivo')} ({_ok(e)})",
    "respaldo": lambda e: f"respaldo de internet: {e.get('accion')} ({_ok(e)})",
    "cable": lambda e: f"cable del celular: {e.get('accion')} ({e.get('interfaz')})",
}


@resiste(str)
def describir(evento: dict[str, Any]) -> str:
    """La frase del evento: la que trae en "texto" o una armada segun su tipo."""
    if evento.get("texto"):
        return str(evento["texto"])
    tipo = str(evento.get("tipo"))
    frase = FRASES.get(tipo)
    if frase:
        return str(frase(evento))
    return str(evento.get("detalle") or tipo)


@resiste(str)
def linea(evento: dict[str, Any]) -> str:
    hora = str(evento.get("hora", ""))[:19].replace("T", " ")
    equipo = EQUIPOS.get(str(evento.get("equipo")), str(evento.get("equipo")))
    return f"{hora}  {equipo:<9}  {describir(evento)}"
