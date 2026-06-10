"""
Build Acquedotto del Fiora runtime data.

Creates:
  - backend/data/mappa-qualita-fiora.json
  - backend/data/pdfs/fiora_<id_layer>_<comune>_<zona>.pdf

Sources:
  - backend/fiora_pdf/*.pdf
  - official Fiora KML embedded in the "Qualita dell'acqua" page.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import requests

HERE = Path(__file__).resolve().parent
SRC_DIR = HERE / "fiora_pdf"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-fiora.json"
KML_CACHE = DATA_DIR / "fiora_poligoni.kml"
POLY_CACHE_FILE = DATA_DIR / "fiora_polygons_cache.json"

PROVIDER_INFO = {
    "label": "Acquedotto del Fiora S.p.A.",
    "ato": "Autorita Idrica Toscana - Conferenza Territoriale n.6 Ombrone",
    "url": "https://www.fiora.it/azienda/acqua-e-territorio/qualita-dellacqua/",
}

KML_URL = "https://www.fiora.it/wp-content/plugins/kaliacqua/public/poligoni.kml?ver=1.1.3"
_HEADERS = {"User-Agent": "AcquaMap-build/1.0 (fiora)"}
ISTAT_GEOJSON = DATA_DIR / "istat_comuni_italia.geojson"
_NAME_ALIAS = {
    "san giovanni d asso": "montalcino",
}


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def _clean(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


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


def _center(geom: dict) -> tuple[float, float]:
    points = list(_iter_points(geom.get("coordinates", [])))
    lons = [float(p[0]) for p in points]
    lats = [float(p[1]) for p in points]
    return (min(lats) + max(lats)) / 2.0, (min(lons) + max(lons)) / 2.0


def load_kml_text() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if KML_CACHE.exists():
        return KML_CACHE.read_text(encoding="utf-8")
    response = requests.get(KML_URL, headers=_HEADERS, timeout=120)
    response.raise_for_status()
    KML_CACHE.write_text(response.text, encoding="utf-8")
    return response.text


def _parse_coords(text: str | None) -> list[list[float]]:
    points: list[list[float]] = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            points.append([float(parts[0]), float(parts[1])])
        except ValueError:
            continue
    if points and points[0] != points[-1]:
        points.append(points[0])
    return points


def _polygon_from_kml(poly: ET.Element, ns: dict[str, str]) -> list[list[list[float]]] | None:
    outer_el = poly.find(".//k:outerBoundaryIs/k:LinearRing/k:coordinates", ns)
    outer = _parse_coords(outer_el.text if outer_el is not None else "")
    if len(outer) < 4:
        return None
    rings = [outer]
    for inner_el in poly.findall(".//k:innerBoundaryIs/k:LinearRing/k:coordinates", ns):
        inner = _parse_coords(inner_el.text)
        if len(inner) >= 4:
            rings.append(inner)
    return rings


def load_kml_polygons() -> dict[str, dict]:
    root = ET.fromstring(load_kml_text().encode("utf-8"))
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    out: dict[str, dict] = {}
    for placemark in root.findall(".//k:Placemark", ns):
        name_el = placemark.find("k:name", ns)
        desc_el = placemark.find("k:description", ns)
        label = _clean(name_el.text if name_el is not None else "")
        desc = _clean(desc_el.text if desc_el is not None else "")
        m = re.search(r"FIQBAC\d+", desc)
        if not m:
            continue
        polygons = []
        for poly in placemark.findall(".//k:Polygon", ns):
            rings = _polygon_from_kml(poly, ns)
            if rings:
                polygons.append(rings)
        if not polygons:
            continue
        geom = (
            {"type": "Polygon", "coordinates": polygons[0]}
            if len(polygons) == 1
            else {"type": "MultiPolygon", "coordinates": polygons}
        )
        out[m.group(0)] = {"label": label, "geometry": geom}
    return out


def load_istat_polygons() -> dict[str, dict]:
    if not ISTAT_GEOJSON.exists():
        return {}
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        if props.get("reg_name") != "Toscana":
            continue
        name = props.get("name") or ""
        if name and feat.get("geometry"):
            out[_normalize(name)] = feat["geometry"]
    return out


def parse_pdf_metadata(path: Path) -> dict:
    meta = {
        "id_layer": "",
        "comune": "",
        "zona": "",
        "nome_kml": "",
        "periodo": "",
    }
    with pdfplumber.open(path) as pdf:
        tables = pdf.pages[0].extract_tables() or []
    if tables:
        for row in tables[0]:
            if not row or len(row) < 2:
                continue
            key = _clean(row[0]).lower()
            val = _clean(row[1])
            if key == "id layer":
                meta["id_layer"] = val
            elif key == "comune":
                meta["comune"] = val
            elif key == "zona":
                meta["zona"] = val
            elif key == "nome kml":
                meta["nome_kml"] = val
            elif key == "periodo":
                meta["periodo"] = val
    if not meta["id_layer"]:
        m = re.match(r"(FIQBAC\d+)", path.stem, re.I)
        meta["id_layer"] = m.group(1).upper() if m else path.stem
    if not meta["comune"]:
        parts = path.stem.split("_", 2)
        if len(parts) >= 2:
            meta["comune"] = parts[1].replace("_", " ")
    if not meta["zona"]:
        parts = path.stem.split("_", 2)
        if len(parts) == 3:
            meta["zona"] = parts[2].replace("_", " ")
    return meta


def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SRC_DIR.exists():
        print(f"[!] sorgente non trovata: {SRC_DIR}")
        return 1

    print("[1/4] carica poligoni Fiora KML...")
    polygons = load_kml_polygons()
    print(f"   poligoni KML: {len(polygons)}")
    istat_polygons = load_istat_polygons()

    print("[2/4] discovery PDF Fiora...")
    features = []
    cache = {}
    skipped = []
    for pdf in sorted(SRC_DIR.glob("*.pdf")):
        meta = parse_pdf_metadata(pdf)
        poly = polygons.get(meta["id_layer"])
        geometry_source = "fiora_kml"
        if not poly:
            comune_key = _NAME_ALIAS.get(_normalize(meta["comune"]), _normalize(meta["comune"]))
            geom = istat_polygons.get(comune_key)
            if not geom:
                skipped.append((pdf.name, f"ID layer assente nel KML: {meta['id_layer']}"))
                continue
            poly = {"label": meta["nome_kml"] or meta["zona"], "geometry": geom}
            geometry_source = "istat_comune_fallback"
        zone_label = meta["zona"] or poly["label"] or meta["id_layer"]
        comune = meta["comune"] or ""
        name = f"fiora_{slugify(meta['id_layer'])}_{slugify(comune)}_{slugify(zone_label)[:70]}"
        dest = PDF_OUT_DIR / f"{name}.pdf"
        shutil.copy2(pdf, dest)
        lat, lon = _center(poly["geometry"])
        props = {
            "name": name,
            "comune": comune.title(),
            "zona_label": zone_label,
            "regione": "Toscana",
            "provider": "toscana_fiora",
            "provider_label": PROVIDER_INFO["label"],
            "provider_ato": PROVIDER_INFO["ato"],
            "lat": lat,
            "lon": lon,
            "id_layer": meta["id_layer"],
            "nome_kml": meta["nome_kml"] or poly["label"],
            "periodo": meta["periodo"],
            "geometry_source": geometry_source,
        }
        features.append({"type": "Feature", "geometry": poly["geometry"], "properties": props})
        cache[name] = {
            "id_layer": meta["id_layer"],
            "comune": comune,
            "zona": zone_label,
            "lat": lat,
            "lon": lon,
        }

    print(f"   validi: {len(features)} / skippati: {len(skipped)}")

    print(f"[3/4] scrive {OUT_GEOJSON.name}...")
    OUT_GEOJSON.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
        "_built_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    POLY_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    print("[4/4] done")
    try:
        from clip_acque_by_fiora import clip_acque_by_fiora
        clip_stats = clip_acque_by_fiora(verbose=False)
        if clip_stats["changed"]:
            print(f"   clip Acque x Fiora: {clip_stats['changed']} feature ritagliate")
    except Exception as exc:
        print(f"   clip Acque x Fiora saltato: {exc}")
    if skipped:
        for name, reason in skipped:
            print(f"   - {name}: {reason}")
    return 0 if not skipped else 2


if __name__ == "__main__":
    sys.exit(main())
