"""
Integrazione fonti esterne ufficiali sulla qualità dell'acqua a Roma:
  - ISPRA: Rete di monitoraggio acque sotterranee di Roma (pozzi e piezometri).
  - Portale Acque Salute (Ministero): link diretto al portale per ricerca per comune.
  - G3W Suite Città Metropolitana Roma: link diretto alla mappa "Tutela acque".

I dati ISPRA sono recuperati via ArcGIS REST e cachati su disco (24h)
per evitare di chiamare il server pubblico ad ogni richiesta.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

import requests

DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)
WELLS_FILE = DATA / "ispra_wells_roma.json"
WELLS_TTL = 24 * 3600  # 24 ore

ARCGIS_WELLS = (
    "https://sinacloud.isprambiente.it/arcgisgeo/rest/services/"
    "Retedimonitoraggiopozziroma/GEO_APP_rete_monitoraggio_roma_edit/"
    "FeatureServer/0/query"
)

# Decodifiche human-friendly dei codici ArcGIS.
_TIPO_OPERA = {
    "poza": "Pozzo per acqua",
    "piez": "Piezometro",
    "post": "Pozzo stratigrafico",
    "spec": "Speciale",
    "grup": "Gruppo di pozzi",
    "altr": "Altro",
}
_FALDA = {
    "falda_regionale": "Falda regionale",
    "falda_ghiaie": "Falda delle ghiaie di base",
    "falda_profonda_albano": "Falda profonda del settore Albano",
    "falda_superficiale": "Falda superficiale",
    "NC": "Non classificabile",
}
_UTILIZZO = {
    "agr": "Agricolo",
    "ind": "Industriale",
    "acq": "Acquedotto",
    "idr": "Idroelettrico",
    "com": "Domestico",
    "pub": "Pubblico",
}
_ATTIVITA = {
    "att": "Attivo",
    "non": "Non attivo",
    "ost": "Ostruito",
    "ind": "Non determinabile",
}
_PRESSIONE = {
    "lib": "Libera",
    "inp": "In pressione",
    "art": "Artesiana",
    "nov": "Non verificata",
}
_MUNICIPIO = {f"m{i}": f"Municipio {i}" for i in range(1, 16)}


def _decode(d: dict, key: str, mapping: dict) -> str | None:
    v = d.get(key)
    if not v:
        return None
    return mapping.get(v, v)


def _fetch_wells_remote() -> dict:
    """Chiama ArcGIS REST per scaricare pozzi/piezometri accessibili (campionabili)."""
    params = {
        "where": "accessibilita='mica'",   # solo punti misurabili/campionabili
        "outFields": "*",
        "f": "geojson",
        "outSR": "4326",
    }
    r = requests.get(ARCGIS_WELLS, params=params, timeout=60,
                     headers={"User-Agent": "HydroMap/1.0"})
    r.raise_for_status()
    raw = r.json()

    items: list[dict[str, Any]] = []
    for f in raw.get("features", []):
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        p = f.get("properties") or {}
        items.append({
            "id": p.get("objectid") or p.get("globalid"),
            "sigla": p.get("sigla"),
            "localita": p.get("localita"),
            "lat": lat, "lng": lon,
            "tipo_opera": _decode(p, "tipo_opera", _TIPO_OPERA),
            "falda": _decode(p, "acquifero", _FALDA),
            "utilizzo": _decode(p, "utilizzo", _UTILIZZO),
            "attivita": _decode(p, "attivita", _ATTIVITA),
            "pressione": _decode(p, "pressione", _PRESSIONE),
            "municipio": _decode(p, "municipio", _MUNICIPIO),
            "profondita_m": p.get("profondita"),
            "quota_m": p.get("quota_pc"),
            "ente": p.get("ente"),
            "data_rilevamento": p.get("data_rilevamento"),
            "ultimo_livello": p.get("rl1_25") or p.get("rl1_24") or p.get("rl1_23"),
        })
    return {
        "items": items,
        "count": len(items),
        "fetched_at": int(time.time()),
        "source": "ISPRA — Rete monitoraggio acque sotterranee Roma",
        "source_url": "https://sinacloud.isprambiente.it/portal/apps/webappviewer/index.html?id=8e503e563996418bade74c4487825ac0",
    }


def get_ispra_wells(force: bool = False) -> dict:
    """Restituisce i pozzi/piezometri ISPRA di Roma (cache disco 24h)."""
    if not force and WELLS_FILE.exists():
        try:
            cached = json.loads(WELLS_FILE.read_text(encoding="utf-8"))
            if (time.time() - cached.get("fetched_at", 0)) < WELLS_TTL:
                return cached
        except Exception:
            pass
    try:
        data = _fetch_wells_remote()
        WELLS_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data
    except Exception as e:
        # In caso di errore restituisci la cache scaduta se presente, altrimenti errore.
        if WELLS_FILE.exists():
            try:
                cached = json.loads(WELLS_FILE.read_text(encoding="utf-8"))
                cached["stale"] = True
                cached["error"] = str(e)
                return cached
            except Exception:
                pass
        return {"items": [], "count": 0, "error": str(e)}


# Fonti istituzionali con link diretti per l'utente.
OFFICIAL_SOURCES = [
    {
        "id": "ispra",
        "title": "ISPRA — Acque sotterranee Roma",
        "description": "Rete di monitoraggio dei pozzi e piezometri convenzionati ISPRA / Roma Capitale. Livello della falda, pH, conducibilità, temperatura.",
        "url": "https://sinacloud.isprambiente.it/portal/apps/webappviewer/index.html?id=8e503e563996418bade74c4487825ac0",
        "agency": "ISPRA (Ministero Ambiente)",
        "type": "WebGIS",
    },
    {
        "id": "salute",
        "title": "Ministero Salute — Acque destinate al consumo umano",
        "description": "Mappa nazionale con i controlli ASL sull'acqua potabile. Cerca 'Roma' nel campo comuni per filtrare i campionamenti del territorio.",
        "url": "https://www.portaleacque.salute.gov.it/PortaleAcquePubblico/mappa",
        "agency": "Ministero della Salute",
        "type": "Mappa interattiva",
        "hint": "Nella ricerca digita ROMA → seleziona il comune → clicca sui punti di campionamento.",
    },
    {
        "id": "g3w",
        "title": "Città Metropolitana Roma — Tutela delle acque",
        "description": "Corridoi fluviali Tevere/Aniene, zone di rispetto delle captazioni, aree di salvaguardia idrogeologica.",
        "url": "https://g3w-suite.cittametropolitanaroma.it/it/map/tutela-acque/",
        "agency": "Città Metropolitana di Roma Capitale",
        "type": "WebGIS",
    },
]
