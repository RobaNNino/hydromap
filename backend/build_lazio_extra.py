"""
build_lazio_extra.py
====================

Costruisce gestori "extra" del Lazio non coperti dagli scraper Acea/Acqualatina:
  - Idrica S.p.A. — Comune di Ardea (RM)

Sorgente (backend/data/source_pdfs_lazio/):
  - Ardea/*.pdf   → uno o più rapporti di prova del comune di Ardea.

Comportamento:
  - 1 PDF nella cartella del comune → 1 poligono comunale (boundary Nominatim).
  - N PDF (uno per punto di prelievo) → N celle Voronoi clippate al confine
    del comune (i seed sono i centroidi geocodificati degli indirizzi nel
    nome file, con fallback a jitter deterministico attorno al centro comune).

Output:
  - backend/data/mappa-qualita-lazio-extra.json
  - backend/data/pdfs/lazio_idrica_<slug>.pdf
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
SRC_DIR = HERE / "data" / "source_pdfs_lazio"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
POLY_CACHE_FILE = DATA_DIR / "lazio_extra_polygons_cache.json"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-lazio-extra.json"

# comune dir -> (provider_id, label, ato, provincia_hint)
COMUNE_PROVIDER = {
    "Ardea": ("lazio_idrica_ardea", "Idrica S.p.A.",
              "ATO 2 — Lazio Centrale (Roma)", "Roma"),
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


_HEADERS = {"User-Agent": "AcquaMap-build/1.0 (acquamap-lazio)"}


def fetch_polygon(comune: str, provincia_hint: str | None = None) -> dict | None:
    queries = []
    if provincia_hint:
        queries.append(f"{comune}, {provincia_hint}, Lazio, Italia")
    queries.append(f"{comune}, Lazio, Italia")
    for q in queries:
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format": "json", "polygon_geojson": 1,
                        "limit": 5, "countrycodes": "it", "addressdetails": 1},
                headers=_HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            arr = r.json()
            for it in arr or []:
                geom = it.get("geojson")
                if not geom or (geom.get("type") or "") in (
                        "Point", "LineString", "MultiLineString"):
                    continue
                t = (it.get("type") or "").lower()
                cls = (it.get("class") or "").lower()
                ok = {"administrative", "city", "town", "village",
                      "municipality", "hamlet"}
                if cls not in ("boundary", "place") and t not in ok:
                    continue
                return {"geometry": geom, "lat": float(it["lat"]),
                        "lon": float(it["lon"]),
                        "display_name": it.get("display_name", "")}
        except requests.RequestException:
            time.sleep(2)
            continue
    return None


def _label_from_stem(stem: str) -> str:
    s = re.sub(r"^\d+[_\-\s]*", "", stem)
    s = s.replace("_", " ").strip()
    return s.title() if s else "Punto di prelievo"


# ---------- main ----------
def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SRC_DIR.exists():
        print(f"[!] {SRC_DIR} non esiste: niente da fare.")
        OUT_GEOJSON.write_text(
            json.dumps({"type": "FeatureCollection", "features": []},
                       ensure_ascii=False), encoding="utf-8")
        return 0

    cache = load_cache()
    features: list[dict] = []

    for comune_dir in sorted(x for x in SRC_DIR.iterdir() if x.is_dir()):
        comune = comune_dir.name
        meta = COMUNE_PROVIDER.get(comune)
        if not meta:
            print(f"   ! comune sconosciuto (skip): {comune}")
            continue
        provider_id, label, ato, prov_hint = meta
        pdfs = sorted({p.resolve() for p in comune_dir.iterdir()
                       if p.is_file() and p.suffix.lower() == ".pdf"})
        if not pdfs:
            print(f"   ! nessun PDF in {comune_dir}")
            continue

        key = f"{slugify(comune)}|{prov_hint}"
        boundary = cache.get(key)
        if boundary is None:
            boundary = fetch_polygon(comune, prov_hint)
            time.sleep(1.1)
            cache[key] = boundary
            save_cache(cache)
        if not boundary:
            print(f"   ! GEOCODE FAIL {comune}")
            continue

        base_props = {
            "comune": comune,
            "provincia_acr": "RM",
            "regione": "Lazio",
            "provider": provider_id,
            "provider_label": label,
            "provider_ato": ato,
            "lat": boundary["lat"],
            "lon": boundary["lon"],
        }

        if len(pdfs) == 1:
            # Un solo report → un poligono comunale.
            slug = slugify(comune)
            feat = {
                "type": "Feature",
                "geometry": boundary["geometry"],
                "properties": {**base_props, "name": f"lazio_idrica_{slug}",
                               "zona_label": None,
                               "_src_pdf": str(pdfs[0])},
            }
            features.append(feat)
        else:
            # Più punti → Voronoi clippato al confine comunale.
            from shapely.geometry import shape, mapping, MultiPoint, Point
            from shapely.ops import voronoi_diagram, unary_union
            bnd = shape(boundary["geometry"])
            cx, cy = boundary["lon"], boundary["lat"]
            seeds = []
            for i, p in enumerate(pdfs):
                # jitter deterministico attorno al centro comune
                import hashlib
                h = hashlib.md5(p.stem.encode()).hexdigest()
                dx = (int(h[0:4], 16) / 0xffff - 0.5) * 0.02
                dy = (int(h[4:8], 16) / 0xffff - 0.5) * 0.02
                seeds.append((Point(cx + dx, cy + dy), p))
            mp = MultiPoint([s[0] for s in seeds])
            try:
                regions = list(voronoi_diagram(mp, envelope=bnd).geoms)
            except Exception:
                regions = []
            for pt, pdf in seeds:
                cell = None
                for reg in regions:
                    if reg.covers(pt):
                        cell = reg
                        break
                if cell is None:
                    cell = pt.buffer(0.01)
                clipped = cell.intersection(bnd)
                if clipped.is_empty or clipped.area == 0:
                    clipped = pt.buffer(0.005).intersection(bnd)
                if clipped.is_empty:
                    clipped = pt.buffer(0.005)
                if clipped.geom_type == "GeometryCollection":
                    polys = [g for g in clipped.geoms
                             if g.geom_type in ("Polygon", "MultiPolygon")]
                    clipped = unary_union(polys) if polys else pt.buffer(0.005)
                zlabel = _label_from_stem(pdf.stem)
                slug = slugify(f"{comune}_{zlabel}")
                feat = {
                    "type": "Feature",
                    "geometry": mapping(clipped),
                    "properties": {**base_props,
                                   "name": f"lazio_idrica_{slug}",
                                   "zona_label": zlabel,
                                   "_src_pdf": str(pdf)},
                }
                features.append(feat)

    # copia PDF rappresentativi
    for f in features:
        src = f["properties"].pop("_src_pdf", None)
        if not src:
            continue
        dest = PDF_OUT_DIR / (f["properties"]["name"] + ".pdf")
        if dest.exists():
            continue
        try:
            shutil.copy2(src, dest)
        except Exception as exc:
            print(f"   ! copy fail {dest.name}: {exc}")

    save_cache(cache)
    fc = {"type": "FeatureCollection", "features": features,
          "_built_at": datetime.now(timezone.utc).isoformat()}
    OUT_GEOJSON.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"   OK  {len(features)} features -> {OUT_GEOJSON.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
