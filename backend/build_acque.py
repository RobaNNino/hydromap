"""
Build Acque S.p.A. runtime data.

Creates:
  - backend/data/mappa-qualita-acque.json
  - backend/data/pdfs/acque_<ris_code>.pdf

Source:
  - backend/acque_pdf/RIS/*.pdf

The RIS PDFs do not include coordinates. The builder geocodes the RIS/locality
label once, stores the result in a cache, then assigns the point to the real
ISTAT municipal polygon.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import requests

HERE = Path(__file__).resolve().parent
SRC_DIR = HERE / "acque_pdf" / "RIS"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
ISTAT_GEOJSON = DATA_DIR / "istat_comuni_italia.geojson"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-acque.json"
GEO_CACHE_FILE = DATA_DIR / "acque_geocode_cache.json"
POLY_CACHE_FILE = DATA_DIR / "acque_polygons_cache.json"

PROVIDER_INFO = {
    "label": "Acque S.p.A.",
    "ato": "Autorita Idrica Toscana - Conferenza Territoriale n.2 Basso Valdarno",
    "url": "https://www.acque.net/",
}

_HEADERS = {"User-Agent": "AcquaMap-build/1.0 (acquamap-acque)"}
_SLEEP = float(os.environ.get("ACQUEMAP_NOMINATIM_SLEEP", "1.0"))

_NAME_ALIAS = {
    "lorenzana": "crespina lorenzana",
    "crespina": "crespina lorenzana",
    "crespina lorenzana": "crespina lorenzana",
}

_MANUAL_COMMUNE_BY_LABEL = {
    "ancellata": "marliana",
    "badalucco": "fauglia",
    "boldrace": "montopoli in val d arno",
    "capitati": "vinci",
    "cavicchio": "montecatini terme",
    "ferchia": "pescia",
    "stecchino": "capannori",
    "stiavelli": "pescia",
}


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", s.lower()).strip()


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


def load_istat_index() -> tuple[list[dict], dict[str, dict]]:
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    index = []
    by_name = {}
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if props.get("reg_name") != "Toscana":
            continue
        geom = feature.get("geometry")
        if not geom or not props.get("name"):
            continue
        minlon, minlat, maxlon, maxlat = _bbox(geom)
        lat, lon = _center(geom)
        item = {
            "bbox": (minlon, minlat, maxlon, maxlat),
            "geometry": geom,
            "name": props["name"],
            "regione": props.get("reg_name"),
            "provincia": props.get("prov_name"),
            "lat": lat,
            "lon": lon,
        }
        index.append(item)
        by_name[_normalize(props["name"])] = item
    return index, by_name


def find_containing(index: list[dict], lat: float, lon: float) -> dict | None:
    for item in index:
        minlon, minlat, maxlon, maxlat = item["bbox"]
        if minlon <= lon <= maxlon and minlat <= lat <= maxlat:
            if _contains(item["geometry"], lon, lat):
                return item
    return None


def parse_entry(path: Path) -> dict | None:
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""
    m_code = re.search(r"Codice\s+(RIS\d+)", text)
    m_zone = re.search(r"RIS:\s*(.+)", text)
    if not m_code:
        m_code = re.match(r"(RIS\d+)", path.stem)
    if not m_code:
        return None
    code = m_code.group(1)
    zone = m_zone.group(1).strip() if m_zone else path.stem
    label = re.sub(r"^RIS\d+\s*[-_ ]\s*", "", zone).replace("_", " ").strip()
    return {"code": code, "label": label, "path": path}


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(path: Path, cache: dict) -> None:
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _query_variants(label: str) -> list[str]:
    raw_parts = [
        _normalize(p)
        for p in re.split(r"\s+-\s+|-", label)
        if _normalize(p)
    ]
    clean = _normalize(label)
    clean = re.sub(r"\b(dep|serb|sorgente|centrale|pozzo|pozz[oi]|acquedotto)\b", " ", clean)
    clean = re.sub(r"\bris\d+\b|\d+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    variants = [clean]
    if len(raw_parts) > 1:
        variants.extend(reversed(raw_parts))
        variants.extend(raw_parts)
    words = clean.split()
    if len(words) > 2:
        variants.append(" ".join(words[-2:]))
    if len(words) > 1:
        variants.append(words[-1])
    out = []
    seen = set()
    for v in variants:
        v = v.strip()
        if len(v) < 4 or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _match_commune_from_label(label: str, by_name: dict[str, dict]) -> dict | None:
    normalized = _normalize(label)
    for needle, commune in _MANUAL_COMMUNE_BY_LABEL.items():
        if needle in normalized:
            return by_name.get(commune)
    normalized = _NAME_ALIAS.get(normalized, normalized)
    if normalized in by_name:
        return by_name[normalized]
    haystack = f" {normalized} "
    matches = []
    for key, item in by_name.items():
        if len(key) >= 5 and f" {key} " in haystack:
            matches.append((len(key), item))
    if matches:
        return sorted(matches, reverse=True, key=lambda x: x[0])[0][1]
    return None


def geocode_label(label: str, cache: dict) -> dict | None:
    cache_key = _normalize(label)
    if cache_key in cache and cache[cache_key] is not None:
        return cache[cache_key]

    for variant in _query_variants(label):
        query = f"{variant}, Toscana, Italia"
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 3, "countrycodes": "it"},
                headers=_HEADERS,
                timeout=30,
            )
            r.raise_for_status()
            results = r.json()
        except requests.RequestException:
            results = []
        time.sleep(_SLEEP)
        for item in results:
            lat = float(item["lat"])
            lon = float(item["lon"])
            display = item.get("display_name", "")
            if "Toscana" in display or "Tuscany" in display:
                cache[cache_key] = {"lat": lat, "lon": lon, "display_name": display}
                return cache[cache_key]

    cache[cache_key] = None
    return None


def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SRC_DIR.exists():
        print(f"[!] sorgente non trovata: {SRC_DIR}")
        return 1

    print("[1/5] carica poligoni ISTAT Toscana...")
    istat, by_name = load_istat_index()
    print(f"   poligoni caricati: {len(istat)}")

    print("[2/5] discovery PDF Acque...")
    entries = [e for p in sorted(SRC_DIR.glob("*.pdf")) if (e := parse_entry(p))]
    print(f"   totale: {len(entries)}")

    geo_cache = load_cache(GEO_CACHE_FILE)
    features = []
    poly_cache = {}
    skipped = []
    print("[3/5] geocoding/match localita RIS...")
    for idx, e in enumerate(entries, 1):
        poly = _match_commune_from_label(e["label"], by_name)
        lat = lon = None
        if poly:
            lat = poly["lat"]
            lon = poly["lon"]
        else:
            geo = geocode_label(e["label"], geo_cache)
            if geo:
                lat = geo["lat"]
                lon = geo["lon"]
                poly = find_containing(istat, lat, lon)
        if not poly:
            skipped.append((e["code"], e["label"]))
            print(f"   ! {idx:03d}/{len(entries)} {e['code']} {e['label']} -> skip")
            continue
        e["polygon"] = poly
        e["lat_point"] = lat if lat is not None else poly["lat"]
        e["lon_point"] = lon if lon is not None else poly["lon"]
        features.append(e)
        if idx % 25 == 0:
            print(f"   {idx:03d}/{len(entries)} ok={len(features)} skip={len(skipped)}")
            save_cache(GEO_CACHE_FILE, geo_cache)

    save_cache(GEO_CACHE_FILE, geo_cache)

    print("[4/5] copia PDF rappresentativi...")
    out_features = []
    for e in features:
        name = f"acque_{slugify(e['code'])}"
        dest = PDF_OUT_DIR / f"{name}.pdf"
        shutil.copy2(e["path"], dest)
        poly = e["polygon"]
        props = {
            "name": name,
            "comune": poly["name"],
            "zona_label": e["label"],
            "regione": "Toscana",
            "provider": "toscana_acque",
            "provider_label": PROVIDER_INFO["label"],
            "provider_ato": PROVIDER_INFO["ato"],
            "lat": e["lat_point"],
            "lon": e["lon_point"],
        }
        out_features.append({"type": "Feature", "geometry": poly["geometry"], "properties": props})
        poly_cache[name] = {"comune": poly["name"], "lat": e["lat_point"], "lon": e["lon_point"]}

    print(f"[5/5] scrive {OUT_GEOJSON.name}...")
    OUT_GEOJSON.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": out_features,
        "_built_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    save_cache(POLY_CACHE_FILE, poly_cache)
    try:
        from clip_acque_by_fiora import clip_acque_by_fiora
        clip_stats = clip_acque_by_fiora(verbose=False)
        if clip_stats["changed"]:
            print(
                "   clip Fiora: "
                f"{clip_stats['changed']} feature ritagliate"
            )
    except Exception as exc:
        print(f"   clip Fiora saltato: {exc}")
    print(f"   OK {len(out_features)} feature / skippati {len(skipped)}")
    if skipped:
        for code, label in skipped[:80]:
            print(f"   - {code}: {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
