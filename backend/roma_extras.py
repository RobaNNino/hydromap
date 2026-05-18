"""
Roma extras: nasoni (fontanelle pubbliche) da OSM Overpass + acquedotti storici.
Risultati cachati su disco.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import requests

DATA = Path(__file__).parent / "data"
NASONI_FILE = DATA / "nasoni.json"
AQUEDUCTS_FILE = DATA / "aqueducts.json"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Bounding box ROMA + comuni vicini (lat_min, lon_min, lat_max, lon_max)
ROMA_BBOX = (41.65, 12.20, 42.20, 12.90)


def _fetch_nasoni() -> dict:
    """Query Overpass per fontanelle/drinking_water nell'area di Roma."""
    bbox = f"{ROMA_BBOX[0]},{ROMA_BBOX[1]},{ROMA_BBOX[2]},{ROMA_BBOX[3]}"
    q = f"""
    [out:json][timeout:60];
    (
      node["amenity"="drinking_water"]({bbox});
      node["man_made"="water_tap"]({bbox});
      node["drinking_water"="yes"]({bbox});
    );
    out body 5000;
    """
    r = requests.post(OVERPASS_URL, data={"data": q}, timeout=90,
                      headers={"User-Agent": "HydroMap/1.0"})
    r.raise_for_status()
    data = r.json()
    feats = []
    seen = set()
    for el in data.get("elements", []):
        if el.get("type") != "node":
            continue
        nid = el.get("id")
        if nid in seen:
            continue
        seen.add(nid)
        tags = el.get("tags") or {}
        feats.append({
            "id": nid,
            "lat": el["lat"],
            "lng": el["lon"],
            "name": tags.get("name"),
            "operator": tags.get("operator"),
            "fountain": tags.get("fountain"),
            "bottle": tags.get("bottle"),
            "wheelchair": tags.get("wheelchair"),
            "fee": tags.get("fee"),
            "tags": tags,
        })
    return {"items": feats, "fetched_at": int(time.time()), "count": len(feats)}


def get_nasoni(force: bool = False, ttl: int = 7 * 24 * 3600) -> dict:
    if not force and NASONI_FILE.exists():
        try:
            cached = json.loads(NASONI_FILE.read_text(encoding="utf-8"))
            if time.time() - cached.get("fetched_at", 0) < ttl:
                return cached
        except Exception:
            pass
    try:
        data = _fetch_nasoni()
        NASONI_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data
    except Exception as e:
        # fallback su cache anche scaduta se c'è
        if NASONI_FILE.exists():
            try:
                cached = json.loads(NASONI_FILE.read_text(encoding="utf-8"))
                cached["stale_reason"] = str(e)
                return cached
            except Exception:
                pass
        return {"items": [], "count": 0, "error": str(e)}


# ---------- ACQUEDOTTI STORICI ----------
# Coordinate tracciate a mano: sorgente -> punto urbano (terminale), approssimative.
# Sufficienti a dare il senso del flusso d'acqua verso Roma.
AQUEDUCTS = [
    {
        "name": "Acquedotto Vergine (Acqua Vergine)",
        "year": "19 a.C.",
        "builder": "Marco Vipsanio Agrippa",
        "length_km": 21,
        "still_active": True,
        "feeds": "Fontana di Trevi, Barcaccia, Quattro Fiumi",
        "color": "#0ea5e9",
        "path": [
            [41.9700, 12.6010],  # Salone (sorgenti Aniene)
            [41.9489, 12.5500],
            [41.9367, 12.5210],
            [41.9223, 12.5006],
            [41.9009, 12.4833],  # Trevi
        ],
    },
    {
        "name": "Acquedotto Marcio (Acqua Marcia)",
        "year": "144 a.C.",
        "builder": "Quinto Marcio Re",
        "length_km": 91,
        "still_active": False,
        "feeds": "Capitolino, Aventino (storicamente)",
        "color": "#9333ea",
        "path": [
            [41.9290, 13.0922],  # Subiaco sorgenti
            [41.9415, 12.9700],
            [41.9520, 12.8500],
            [41.9090, 12.7300],
            [41.8950, 12.6500],
            [41.8911, 12.5158],  # Porta Maggiore
        ],
    },
    {
        "name": "Acquedotto Felice (Acqua Felice)",
        "year": "1586",
        "builder": "Papa Sisto V",
        "length_km": 24,
        "still_active": True,
        "feeds": "Mosè (Piazza San Bernardo), fontane storiche",
        "color": "#16a34a",
        "path": [
            [41.8175, 12.7480],  # Pantano dei Grifi (Colonna)
            [41.8400, 12.6900],
            [41.8730, 12.6200],
            [41.8889, 12.5780],
            [41.9036, 12.4961],  # San Bernardo
        ],
    },
    {
        "name": "Acquedotto Paolo (Acqua Paola)",
        "year": "1612",
        "builder": "Papa Paolo V",
        "length_km": 60,
        "still_active": True,
        "feeds": "Gianicolo (Fontanone), Trastevere",
        "color": "#ea580c",
        "path": [
            [42.0950, 12.1880],  # Lago di Bracciano
            [42.0700, 12.2400],
            [42.0200, 12.3000],
            [41.9610, 12.3700],
            [41.9216, 12.4400],
            [41.8930, 12.4640],  # Gianicolo
        ],
    },
    {
        "name": "Acquedotto Peschiera-Capore",
        "year": "1949 / 1980",
        "builder": "Acea",
        "length_km": 130,
        "still_active": True,
        "feeds": "≈ 70% acqua potabile di Roma oggi",
        "color": "#dc2626",
        "path": [
            [42.4150, 12.9550],  # Peschiera (Cittaducale)
            [42.3700, 12.8500],
            [42.3200, 12.7400],
            [42.2700, 12.6800],
            [42.1900, 12.6500],
            [42.0700, 12.6000],
            [41.9700, 12.5400],
            [41.9028, 12.4964],  # Roma
        ],
    },
    {
        "name": "Acquedotto Anio Vetus",
        "year": "272 a.C.",
        "builder": "Manio Curio Dentato",
        "length_km": 64,
        "still_active": False,
        "feeds": "(antico) — uso non potabile",
        "color": "#7c2d12",
        "path": [
            [41.9050, 13.0500],  # Tivoli alta
            [41.9220, 12.9300],
            [41.9090, 12.8000],
            [41.8980, 12.6700],
            [41.8911, 12.5158],  # Porta Maggiore
        ],
    },
    {
        "name": "Acquedotto Claudio (Aqua Claudia)",
        "year": "52 d.C.",
        "builder": "Imperatori Caligola/Claudio",
        "length_km": 69,
        "still_active": False,
        "feeds": "(antico) — Parco degli Acquedotti",
        "color": "#a16207",
        "path": [
            [41.9550, 13.1700],  # Subiaco
            [41.9300, 13.0500],
            [41.8900, 12.9000],
            [41.8560, 12.7800],  # Parco Acquedotti
            [41.8800, 12.6500],
            [41.8911, 12.5158],
        ],
    },
]


def get_aqueducts() -> dict:
    feats = []
    for a in AQUEDUCTS:
        feats.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon, lat] for lat, lon in a["path"]],
            },
            "properties": {k: v for k, v in a.items() if k != "path"},
        })
    return {"type": "FeatureCollection", "features": feats}
