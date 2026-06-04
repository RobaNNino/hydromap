"""
build_molise.py
===============

Costruisce:
  - backend/data/mappa-qualita-molise.json   (GeoJSON poligoni comunali)
  - backend/data/pdfs/molise_<provider>_<slug>.pdf   (PDF rappresentativi)

Sorgente (backend/data/source_pdfs_molise/):
  - Campobasso/                 → capoluogo (1 PDF flat)
  - Provincia_Campobasso/<Comune>/<CODICE>/<pdf>
  - Provincia_Isernia/<Comune>/<CODICE>/<pdf>

Tutti i comuni sono serviti da Acea Molise (provider "molise_acea").
1 poligono comunale per comune (geocodifica Nominatim, cache su disco).
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
SRC_DIR = HERE / "data" / "source_pdfs_molise"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
POLY_CACHE_FILE = DATA_DIR / "molise_polygons_cache.json"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-molise.json"

PROVIDER_INFO = {
    "acea": {
        "label": "Acea Molise S.r.l.",
        "ato": "ATO Unico Molise",
        "url": "https://www.aceamolise.a-acqua.it/qualita-acqua",
    },
}

# Provincia per comune (CB = Campobasso, IS = Isernia). Tutto ciò che non
# è elencato qui usa "CB" come default (la maggioranza dei comuni).
PROV_ISERNIA = {
    "Agnone", "Isernia", "Montaquila", "Pozzilli", "Venafro",
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
def _latest_pdf(folder: Path) -> Path | None:
    pdfs = list(folder.rglob("*.pdf")) + list(folder.rglob("*.PDF"))
    if not pdfs:
        return None
    # Più recente per mtime (i nomi non hanno un formato data uniforme).
    pdfs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return pdfs[0]


def discover_molise() -> list[dict]:
    out: list[dict] = []
    if not SRC_DIR.exists():
        return out

    # 1) Capoluogo Campobasso (cartella flat)
    cb = SRC_DIR / "Campobasso"
    if cb.exists():
        best = _latest_pdf(cb)
        if best:
            out.append({"provider": "acea", "comune": "Campobasso",
                        "pdf": best})

    # 2) Province (una sottocartella per comune)
    for prov_dir in ("Provincia_Campobasso", "Provincia_Isernia"):
        base = SRC_DIR / prov_dir
        if not base.exists():
            continue
        for comune_dir in sorted(x for x in base.iterdir() if x.is_dir()):
            best = _latest_pdf(comune_dir)
            if not best:
                continue
            out.append({"provider": "acea", "comune": comune_dir.name,
                        "pdf": best})
    return out


# ---------- geocoding ----------
_HEADERS = {"User-Agent": "AcquaMap-build/1.0 (acquamap-molise)"}


def fetch_polygon(comune: str, provincia_hint: str | None = None) -> dict | None:
    queries = []
    if provincia_hint:
        queries.append(f"{comune}, {provincia_hint}, Molise, Italia")
    queries.append(f"{comune}, Molise, Italia")
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

    print("[1/4] discovery PDF Molise…")
    entries = discover_molise()
    print(f"   totale: {len(entries)} comuni")

    print("[2/4] geocoding poligoni (Nominatim, ~1s/comune)…")
    cache = load_cache()
    features = []
    skipped: list[str] = []
    n_new = 0
    for i, e in enumerate(entries, 1):
        comune = e["comune"]
        prov = "IS" if comune in PROV_ISERNIA else "CB"
        key = f"acea|{slugify(comune)}"
        info = cache.get(key)
        if info is None:
            info = fetch_polygon(comune, prov)
            n_new += 1
            time.sleep(1.1)
            cache[key] = info
            if n_new % 10 == 0:
                save_cache(cache)
        if not info:
            skipped.append(comune)
            print(f"   ! [{i:2d}] {comune:30s}  GEOCODE FAIL")
            continue
        slug = slugify(comune)
        feat = {
            "type": "Feature",
            "geometry": info["geometry"],
            "properties": {
                "name": f"molise_acea_{slug}",
                "comune": comune,
                "zona_label": None,
                "provincia_acr": prov,
                "regione": "Molise",
                "provider": "molise_acea",
                "provider_label": PROVIDER_INFO["acea"]["label"],
                "provider_ato": PROVIDER_INFO["acea"]["ato"],
                "lat": info["lat"],
                "lon": info["lon"],
            },
        }
        features.append(feat)

    save_cache(cache)
    print(f"   geocodificati: {len(features)}  /  skippati: {len(skipped)}")

    print("[3/4] copia PDF in data/pdfs/ …")
    for f in features:
        slug = "_".join(f["properties"]["name"].split("_")[2:])
        entry = next((e for e in entries if slugify(e["comune"]) == slug), None)
        if not entry:
            continue
        dest = PDF_OUT_DIR / (f["properties"]["name"] + ".pdf")
        if dest.exists():
            continue
        try:
            shutil.copy2(entry["pdf"], dest)
        except Exception as exc:
            print(f"   ! copy fail {dest.name}: {exc}")

    print(f"[4/4] scrive {OUT_GEOJSON.name} …")
    fc = {"type": "FeatureCollection", "features": features,
          "_built_at": datetime.now(timezone.utc).isoformat()}
    OUT_GEOJSON.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"   OK  {len(features)} features")

    if skipped:
        print(f"\n[skipped] {len(skipped)} comuni senza poligono:")
        for com in skipped:
            print(f"   - {com}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
