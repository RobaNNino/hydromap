"""
build_puglia.py
===============

Costruisce:
  - backend/data/mappa-qualita-puglia.json   (GeoJSON poligoni comunali)
  - backend/data/pdfs/puglia_aqp_<slug>.pdf   (PDF rappresentativi)

Sorgente (backend/aqp_pdf/):
  - <Comune>(XX).pdf   (XX = sigla provincia: BA/BR/BT/FG/LE/TA)

Gestore unico regionale: Acquedotto Pugliese S.p.A. (AQP).
1 poligono comunale per comune (geocodifica Nominatim, cache su disco).
I PDF AQP sono testuali (tabella "Parametro | Valore | Limite | Unità").
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SRC_DIR = HERE / "aqp_pdf"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
POLY_CACHE_FILE = DATA_DIR / "puglia_polygons_cache.json"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-puglia.json"

PROVIDER_INFO = {
    "label": "Acquedotto Pugliese S.p.A.",
    "ato": "AIP — Autorità Idrica Pugliese (ATO Unico Puglia)",
    "url": "https://www.aqp.it/qualita-acqua",
}

# Sigla provincia -> nome esteso (hint per la geocodifica Nominatim).
PROV_NAMES = {
    "BA": "Bari",
    "BR": "Brindisi",
    "BT": "Barletta-Andria-Trani",
    "FG": "Foggia",
    "LE": "Lecce",
    "TA": "Taranto",
}


# ---------- utils ----------
def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def load_cache() -> dict:
    if POLY_CACHE_FILE.exists():
        try:
            return json.loads(POLY_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(c: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POLY_CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False),
                               encoding="utf-8")


# ---------- discovery ----------
def discover_puglia() -> list[dict]:
    """Legge i PDF in aqp_pdf/ e ne ricava comune + provincia dal nome file."""
    out: list[dict] = []
    if not SRC_DIR.exists():
        return out
    seen: set[str] = set()
    pdfs = sorted(
        {p for p in SRC_DIR.iterdir()
         if p.is_file() and p.suffix.lower() == ".pdf"},
        key=lambda p: p.name.lower(),
    )
    for pdf in pdfs:
        base = pdf.stem  # es. "San_Donato_di_Lecce_-_Galugnano(LE)"
        m = re.search(r"\(([A-Z]{2})\)\s*$", base)
        prov = m.group(1) if m else None
        name_part = re.sub(r"\([A-Z]{2}\)\s*$", "", base).strip()
        # nome leggibile: underscore -> spazio, normalizza separatore frazione
        label = name_part.replace("_", " ").replace(" - ", " — ").strip()
        # comune principale (per geocodifica): parte prima dell'eventuale "—"
        comune_geo = re.split(r"\s+[—-]\s+", label)[0].strip()
        slug = slugify(name_part)
        if slug in seen:
            continue
        seen.add(slug)
        out.append({
            "slug": slug,
            "label": label,
            "comune_geo": comune_geo,
            "prov": prov,
            "pdf": pdf,
        })
    return out


# ---------- geocoding ----------
_HEADERS = {"User-Agent": "AcquaMap-build/1.0 (acquamap-puglia)"}


def fetch_polygon(comune: str, provincia_hint: str | None) -> dict | None:
    queries = []
    if provincia_hint:
        queries.append(f"{comune}, {provincia_hint}, Puglia, Italia")
    queries.append(f"{comune}, Puglia, Italia")
    for q in queries:
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": q,
                    "format": "json",
                    "polygon_geojson": 1,
                    "limit": 5,
                    "countrycodes": "it",
                    "addressdetails": 1,
                },
                headers=_HEADERS,
                timeout=15,
            )
            if r.status_code != 200:
                continue
            arr = r.json()
            if not arr:
                continue
            ok_types = {"administrative", "city", "town", "village",
                        "municipality", "hamlet"}
            for it in arr:
                geom = it.get("geojson")
                if not geom:
                    continue
                if (geom.get("type") or "") in ("Point", "LineString",
                                                "MultiLineString"):
                    continue
                t = (it.get("type") or "").lower()
                cls = (it.get("class") or "").lower()
                if cls != "boundary" and cls != "place" and t not in ok_types:
                    continue
                return {
                    "geometry": geom,
                    "lat": float(it["lat"]),
                    "lon": float(it["lon"]),
                    "display_name": it.get("display_name", ""),
                }
        except requests.RequestException:
            time.sleep(2)
            continue
    return None


# ---------- main ----------
def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] discovery PDF AQP (aqp_pdf/)…")
    entries = discover_puglia()
    print(f"   totale: {len(entries)} comuni AQP")

    print("[2/4] geocoding poligoni comunali (Nominatim, ~1s/comune)…")
    cache = load_cache()
    features = []
    skipped: list[str] = []
    n_new = 0
    for i, e in enumerate(entries, 1):
        prov = e["prov"]
        prov_name = PROV_NAMES.get(prov or "", None)
        key = f"aqp|{e['slug']}"
        info = cache.get(key)
        if info is None:
            info = fetch_polygon(e["comune_geo"], prov_name)
            n_new += 1
            time.sleep(1.1)
            cache[key] = info
            if n_new % 10 == 0:
                save_cache(cache)
                print(f"   …{i}/{len(entries)} (nuovi geocode: {n_new})")
        if not info:
            skipped.append(e["label"])
            print(f"   ! [{i:3d}] {e['label']:35s}  GEOCODE FAIL")
            continue
        feat = {
            "type": "Feature",
            "geometry": info["geometry"],
            "properties": {
                "name": f"puglia_aqp_{e['slug']}",
                "comune": e["label"],
                "zona_label": None,
                "provincia_acr": prov,
                "regione": "Puglia",
                "provider": "puglia_aqp",
                "provider_label": PROVIDER_INFO["label"],
                "provider_ato": PROVIDER_INFO["ato"],
                "lat": info["lat"],
                "lon": info["lon"],
                "_src_pdf": str(e["pdf"]),
            },
        }
        features.append(feat)
    save_cache(cache)
    print(f"   poligoni totali: {len(features)}  /  skippati: {len(skipped)}")

    print("[3/4] copia PDF in data/pdfs/ …")
    for f in features:
        src = f["properties"].pop("_src_pdf", None)
        if not src:
            continue
        dest = PDF_OUT_DIR / (f["properties"]["name"] + ".pdf")
        try:
            shutil.copy2(src, dest)
        except Exception as exc:
            print(f"   ! copy fail {dest.name}: {exc}")

    print(f"[4/4] scrive {OUT_GEOJSON.name} …")
    fc = {"type": "FeatureCollection", "features": features,
          "_built_at": datetime.now(timezone.utc).isoformat()}
    OUT_GEOJSON.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"   OK  {len(features)} features (poligoni comunali reali)")

    if skipped:
        print(f"\n[skipped] {len(skipped)} comuni senza poligono:")
        for com in skipped:
            print(f"   - {com}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
