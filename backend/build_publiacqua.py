"""
Build Publiacqua runtime data.

Creates:
  - backend/data/mappa-qualita-publiacqua.json
  - backend/data/pdfs/publiacqua_<code>.pdf

Source:
  - backend/publiacqua_pdf/*.pdf

The PDFs include coordinates. Municipal polygons are real ISTAT polygons:
each point is assigned to the containing municipality polygon.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent
SRC_DIR = HERE / "publiacqua_pdf"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
ISTAT_GEOJSON = DATA_DIR / "istat_comuni_italia.geojson"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-publiacqua.json"
POLY_CACHE_FILE = DATA_DIR / "publiacqua_polygons_cache.json"

PROVIDER_INFO = {
    "label": "Publiacqua S.p.A.",
    "ato": "Autorita Idrica Toscana - Conferenza Territoriale n.3 Medio Valdarno",
    "url": "https://www.publiacqua.it/qualita-acqua",
}


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _iter_points(coords):
    if not coords:
        return
    first = coords[0]
    if isinstance(first, (int, float)):
        yield coords
        return
    for item in coords:
        yield from _iter_points(item)


def _bbox(geom: dict) -> tuple[float, float, float, float]:
    points = list(_iter_points(geom.get("coordinates", [])))
    lons = [float(p[0]) for p in points]
    lats = [float(p[1]) for p in points]
    return min(lons), min(lats), max(lons), max(lats)


def _center(geom: dict) -> tuple[float, float]:
    minlon, minlat, maxlon, maxlat = _bbox(geom)
    return (minlat + maxlat) / 2.0, (minlon + maxlon) / 2.0


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _point_in_polygon(lon: float, lat: float, rings: list) -> bool:
    if not rings or not _point_in_ring(lon, lat, rings[0]):
        return False
    return not any(_point_in_ring(lon, lat, hole) for hole in rings[1:])


def _contains(geom: dict, lon: float, lat: float) -> bool:
    if geom.get("type") == "Polygon":
        return _point_in_polygon(lon, lat, geom.get("coordinates", []))
    if geom.get("type") == "MultiPolygon":
        return any(_point_in_polygon(lon, lat, poly) for poly in geom.get("coordinates", []))
    return False


def load_istat_index() -> list[dict]:
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    index = []
    for feature in data.get("features", []):
        geom = feature.get("geometry")
        props = feature.get("properties", {})
        if not geom or not props.get("name"):
            continue
        minlon, minlat, maxlon, maxlat = _bbox(geom)
        lat, lon = _center(geom)
        index.append({
            "bbox": (minlon, minlat, maxlon, maxlat),
            "geometry": geom,
            "name": props["name"],
            "regione": props.get("reg_name"),
            "provincia": props.get("prov_name"),
            "lat": lat,
            "lon": lon,
        })
    return index


def find_containing(index: list[dict], lat: float, lon: float) -> dict | None:
    for item in index:
        minlon, minlat, maxlon, maxlat = item["bbox"]
        if minlon <= lon <= maxlon and minlat <= lat <= maxlat:
            if _contains(item["geometry"], lon, lat):
                return item
    return None


def parse_metadata(path: Path) -> dict | None:
    with pdfplumber.open(path) as pdf:
        tables = pdf.pages[0].extract_tables() or []
    if not tables:
        return None
    meta: dict[str, str] = {}
    for row in tables[0]:
        if row and len(row) >= 2:
            meta[_clean(row[0]).lower()] = _clean(row[1])
    code = meta.get("codice")
    coords = meta.get("coordinate interrogate")
    if not code or not coords:
        return None
    nums = re.findall(r"-?\d+(?:[.,]\d+)?", coords)
    if len(nums) < 2:
        return None
    lat = float(nums[0].replace(",", "."))
    lon = float(nums[1].replace(",", "."))
    return {
        "code": code,
        "slug": slugify(code),
        "reported_comune": meta.get("comune"),
        "address": meta.get("indirizzo"),
        "periodo": meta.get("periodo", "").replace("Periodo di riferimento:", "").strip(),
        "lat_point": lat,
        "lon_point": lon,
        "path": path,
    }


def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SRC_DIR.exists():
        print(f"[!] sorgente non trovata: {SRC_DIR}")
        return 1

    print("[1/4] carica poligoni ISTAT...")
    istat = load_istat_index()
    print(f"   poligoni caricati: {len(istat)}")

    print("[2/4] discovery PDF Publiacqua...")
    entries = []
    skipped = []
    for path in sorted(SRC_DIR.glob("*.pdf")):
        entry = parse_metadata(path)
        if not entry:
            skipped.append((path.name, "metadata"))
            continue
        poly = find_containing(istat, entry["lat_point"], entry["lon_point"])
        if not poly:
            skipped.append((path.name, "polygon"))
            continue
        entry["polygon"] = poly
        entries.append(entry)
    print(f"   validi: {len(entries)} / skippati: {len(skipped)}")

    features = []
    cache = {}
    print("[3/4] copia PDF rappresentativi...")
    for e in entries:
        name = f"publiacqua_{e['slug']}"
        dest = PDF_OUT_DIR / f"{name}.pdf"
        shutil.copy2(e["path"], dest)
        poly = e["polygon"]
        props = {
            "name": name,
            "comune": poly["name"],
            "zona_label": e["address"] or e["reported_comune"] or e["code"],
            "regione": poly["regione"] or "Toscana",
            "provider": "toscana_publiacqua",
            "provider_label": PROVIDER_INFO["label"],
            "provider_ato": PROVIDER_INFO["ato"],
            "lat": e["lat_point"],
            "lon": e["lon_point"],
            "reported_comune": e["reported_comune"],
            "periodo": e["periodo"],
        }
        features.append({"type": "Feature", "geometry": poly["geometry"], "properties": props})
        cache[name] = {"comune": poly["name"], "lat": e["lat_point"], "lon": e["lon_point"]}

    print(f"[4/4] scrive {OUT_GEOJSON.name}...")
    OUT_GEOJSON.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
        "_built_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    POLY_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"   OK {len(features)} feature")
    if skipped:
        print(f"   skippati {len(skipped)}:")
        for name, reason in skipped[:40]:
            print(f"   - {name}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
