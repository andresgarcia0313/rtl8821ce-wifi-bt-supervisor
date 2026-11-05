"""La bitacora contada en frases sencillas."""

from pathlib import Path

from radio_rtw88 import relato
from radio_rtw88.eventos import Bitacora


def test_cada_tipo_tiene_su_frase() -> None:
    falla = {"tipo": "falla", "causa": "zombi"}
    assert relato.describir(falla) == "falla: conectada pero sin trafico (cuelgue silencioso)"
    rem = {"tipo": "remedio", "ok": True, "paso": "reasociar", "segundos": 12.3, "causa": "desasociado"}
    assert relato.describir(rem).startswith("reparada con 'reasociar' en 12.3 s")
    malo = {"tipo": "remedio", "ok": False, "fallidos": ["reasociar", "reset pci"], "causa": "zombi"}
    assert "probados: reasociar, reset pci" in relato.describir(malo)
    assert (
        relato.describir({"tipo": "canal", "texto": "canal limpio -> congestionado"})
        == "canal limpio -> congestionado"
    )


def test_un_evento_raro_no_rompe_el_relato() -> None:
    assert relato.describir({"tipo": "desconocido", "detalle": "algo"}) == "algo"
    assert relato.describir({"tipo": "remedio", "ok": False, "fallidos": 5}).startswith("{")  # alternativa


def test_la_bitacora_guarda_la_frase_y_la_linea_es_legible(tmp_path: Path) -> None:
    b = Bitacora(str(tmp_path))
    b.anotar("wifi", "recuperada_sola", segundos=8.0)
    e = b.ultimos(1)[0]
    assert e["texto"] == "se recupero sola en 8.0 s, sin tocar nada"
    assert relato.linea(e).endswith("Wifi       se recupero sola en 8.0 s, sin tocar nada")
