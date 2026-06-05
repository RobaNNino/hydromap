"""
Build ASA/ASAmap runtime data.

Creates:
  - backend/data/mappa-qualita-asamap.json
  - backend/data/pdfs/asamap_<code>_<comune>.pdf

Source:
  - backend/asamap_pdf/*.pdf
  - ASAmap WFS layer asa_geoserver:etichette for real aqueduct polygons.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3

HERE = Path(__file__).resolve().parent
SRC_DIR = HERE / "asamap_pdf"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-asamap.json"
WFS_CACHE = DATA_DIR / "asamap_wfs_etichette.json"
POLY_CACHE_FILE = DATA_DIR / "asamap_polygons_cache.json"

PROVIDER_INFO = {
    "label": "ASA S.p.A.",
    "ato": "Autorita Idrica Toscana - Conferenza Territoriale n.5 Toscana Costa",
    "url": "https://www.asamap.it/etichette",
}

WFS_URL = "https://asamap.it:8443/geoserver/asa_geoserver/ows"
WFS_PARAMS = {
    "service": "WFS",
    "version": "1.0.0",
    "request": "GetFeature",
    "typeName": "asa_geoserver:etichette",
    "outputFormat": "application/json",
    "srsname": "EPSG:4326",
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


def _center(geom: dict) -> tuple[float, float]:
    points = list(_iter_points(geom.get("coordinates", [])))
    lons = [float(p[0]) for p in points]
    lats = [float(p[1]) for p in points]
    return (min(lats) + max(lats)) / 2.0, (min(lons) + max(lons)) / 2.0


def parse_pdf_name(path: Path) -> dict | None:
    m = re.match(r"(ACQ\d+)_([^_].*?)_ACQ\d+", path.stem, re.I)
    if not m:
        m = re.match(r"(ACQ\d+)_([^_].*)", path.stem, re.I)
    if not m:
        return None
    code = m.group(1).upper()
    comune = m.group(2).replace("_", " ")
    comune = re.sub(r"\s+", " ", comune).strip()
    return {"code": code, "comune_hint": comune, "path": path}


def load_wfs() -> dict:
    if WFS_CACHE.exists():
        return json.loads(WFS_CACHE.read_text(encoding="utf-8"))
    urllib3.disable_warnings()
    response = requests.get(
        WFS_URL,
        params=WFS_PARAMS,
        headers={"User-Agent": "AcquaMap-build/1.0 (asamap)"},
        timeout=120,
        verify=False,
    )
    response.raise_for_status()
    data = response.json()
    WFS_CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SRC_DIR.exists():
        print(f"[!] sorgente non trovata: {SRC_DIR}")
        return 1

    print("[1/4] carica geometrie ASAmap WFS...")
    wfs = load_wfs()
    wfs_features = wfs.get("features", [])
    by_code: dict[str, list[dict]] = {}
    for feat in wfs_features:
        code = (feat.get("properties", {}).get("cod_acq") or "").upper()
        if code:
            by_code.setdefault(code, []).append(feat)
    print(f"   WFS feature: {len(wfs_features)} / codici: {len(by_code)}")

    print("[2/4] discovery PDF ASA...")
    entries = [e for p in sorted(SRC_DIR.glob("*.pdf")) if (e := parse_pdf_name(p))]
    features = []
    cache = {}
    skipped = []
    used_names: set[str] = set()
    for e in entries:
        candidates = by_code.get(e["code"], [])
        if not candidates:
            skipped.append((e["path"].name, "codice WFS assente"))
            continue
        wanted = _normalize(e["comune_hint"])
        source_slug = slugify(e["path"].stem)
        chosen = None
        for feat in candidates:
            link = feat.get("properties", {}).get("link") or ""
            link_slug = slugify(Path(link).stem)
            if link_slug and source_slug.endswith(link_slug):
                chosen = feat
                break
        for feat in candidates:
            if chosen is not None:
                break
            comune = _normalize(feat.get("properties", {}).get("comune") or "")
            if wanted and (wanted in comune or comune in wanted):
                chosen = feat
                break
        if chosen is None:
            chosen = candidates[0]
        props = chosen.get("properties", {})
        comune = props.get("comune") or e["comune_hint"]
        base_name = f"asamap_{slugify(e['code'])}_{slugify(comune)}"
        name = base_name
        if name in used_names:
            link = props.get("link") or e["path"].stem
            suffix = slugify(Path(link).stem)
            name = f"{base_name}_{suffix}"
        used_names.add(name)
        lat, lon = _center(chosen["geometry"])
        dest = PDF_OUT_DIR / f"{name}.pdf"
        shutil.copy2(e["path"], dest)
        out_props = {
            "name": name,
            "comune": str(comune).title(),
            "zona_label": props.get("acquedotto") or e["code"],
            "regione": "Toscana",
            "provider": "toscana_asamap",
            "provider_label": PROVIDER_INFO["label"],
            "provider_ato": PROVIDER_INFO["ato"],
            "lat": lat,
            "lon": lon,
            "cod_acq": e["code"],
            "distretto": props.get("distretto"),
            "luogo_prel": props.get("luogo_prel"),
        }
        features.append({"type": "Feature", "geometry": chosen["geometry"], "properties": out_props})
        cache[name] = {"code": e["code"], "comune": comune, "lat": lat, "lon": lon}
    print(f"   validi: {len(features)} / skippati: {len(skipped)}")

    print(f"[3/4] scrive {OUT_GEOJSON.name}...")
    OUT_GEOJSON.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
        "_built_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    POLY_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    print("[4/4] done")
    if skipped:
        for name, reason in skipped:
            print(f"   - {name}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
