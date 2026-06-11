"""
Build AASS runtime data (Repubblica di San Marino).

Creates:
  - backend/data/mappa-qualita-aass.json
  - backend/data/pdfs/sanmarino_aass_<castello>.pdf

Sources:
  - backend/aass_sm_pdf/<Castello>.pdf   (uno per ciascuno dei 9 castelli)

I poligoni dei 9 castelli (admin_level=8) vengono scaricati da Overpass con
una sola richiesta sull'area ISO3166-1=SM e cachati in
backend/data/sanmarino_castelli_cache.json (gitignored).
"""
from __future__ import annotations

import json
import hashlib
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
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"

SRC_DIR = HERE / "aass_sm_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-aass.json"
CACHE_FILE = DATA_DIR / "sanmarino_castelli_cache.json"

PROVIDER_ID = "sanmarino_aass"
PROVIDER_LABEL = "AASS San Marino"
PROVIDER_ATO = "Repubblica di San Marino"

MAX_FEATURE_NAME_LEN = 80
_HEADERS = {"User-Agent": "AcquaMap/1.0 (build script; contact: repo)"}


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:150].strip("_")


def short_feature_name(prefix: str, label: str, seed: str) -> str:
    slug = slugify(label)
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    room = MAX_FEATURE_NAME_LEN - len(prefix) - len(digest) - 2
    head = slug[:max(12, room)].strip("_")
    return f"{prefix}_{head}_{digest}"


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s.lower())).strip()


# ---------- Overpass: relation -> GeoJSON (stesso pattern di build_nuoveacque) ----------
def _pt_key(p: dict) -> tuple:
    return (round(p["lat"], 7), round(p["lon"], 7))


def _assemble_rings(ways: list[list[dict]]) -> list[list[list[float]]]:
    remaining = [list(w) for w in ways if w and len(w) >= 2]
    rings: list[list[list[float]]] = []
    while remaining:
        chain = remaining.pop(0)
        progress = True
        while progress and _pt_key(chain[0]) != _pt_key(chain[-1]):
            progress = False
            ek = _pt_key(chain[-1])
            for i, w in enumerate(remaining):
                if _pt_key(w[0]) == ek:
                    chain.extend(w[1:])
                    remaining.pop(i)
                    progress = True
                    break
                if _pt_key(w[-1]) == ek:
                    chain.extend(list(reversed(w))[1:])
                    remaining.pop(i)
                    progress = True
                    break
        if _pt_key(chain[0]) != _pt_key(chain[-1]):
            chain.append(chain[0])
        if len(chain) >= 4:
            rings.append([[p["lon"], p["lat"]] for p in chain])
    return rings


def _point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _relation_to_geojson(members: list[dict]) -> dict | None:
    outer_ways = [m["geometry"] for m in members
                  if m.get("type") == "way" and m.get("role") in ("outer", "")
                  and m.get("geometry")]
    inner_ways = [m["geometry"] for m in members
                  if m.get("type") == "way" and m.get("role") == "inner"
                  and m.get("geometry")]
    outer_rings = _assemble_rings(outer_ways)
    if not outer_rings:
        return None
    inner_rings = _assemble_rings(inner_ways)
    if len(outer_rings) == 1:
        return {"type": "Polygon", "coordinates": [outer_rings[0]] + inner_rings}
    polys = [[ring] for ring in outer_rings]
    for ir in inner_rings:
        px, py = ir[0]
        for idx, oring in enumerate(outer_rings):
            if _point_in_ring(px, py, oring):
                polys[idx].append(ir)
                break
        else:
            polys[0].append(ir)
    return {"type": "MultiPolygon", "coordinates": polys}


def fetch_castelli() -> dict[str, dict]:
    """Scarica i poligoni dei 9 castelli di San Marino (admin_level=8)."""
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if cached:
                print(f"   [cache] {len(cached)} castelli da {CACHE_FILE.name}")
                return cached
        except Exception:
            pass
    mirrors = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    query = (
        "[out:json][timeout:120];"
        'area["ISO3166-1"="SM"]["admin_level"="2"]->.sm;'
        'rel["boundary"="administrative"]["admin_level"="8"](area.sm);'
        "out geom;"
    )
    print("   [Overpass] scarica i poligoni dei castelli di San Marino…")
    elements = None
    for url in mirrors:
        for _ in range(2):
            try:
                r = requests.get(url, params={"data": query}, headers=_HEADERS, timeout=150)
                if r.status_code in (429, 502, 503, 504):
                    time.sleep(5)
                    continue
                r.raise_for_status()
                elements = r.json().get("elements", [])
                break
            except requests.RequestException as exc:
                print(f"   [Overpass] {url.split('/')[2]} errore: {exc}")
                time.sleep(3)
        if elements is not None:
            break
    if elements is None:
        print("   ! Overpass: tutti i mirror falliti")
        return {}

    result: dict[str, dict] = {}
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name:it") or tags.get("name") or ""
        if not name:
            continue
        geom = _relation_to_geojson(el.get("members", []))
        if not geom:
            continue
        result[_normalize(name)] = {"display_name": name, "geometry": geom}
    print(f"   [Overpass] ottenuti {len(result)} castelli")
    if result:
        CACHE_FILE.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def _iter_points(coords):
    if not coords:
        return
    if isinstance(coords[0], (int, float)):
        yield coords
        return
    for item in coords:
        yield from _iter_points(item)


def _center(geom: dict) -> tuple[float, float]:
    points = list(_iter_points(geom.get("coordinates", [])))
    if not points:
        return 0.0, 0.0
    lons = [float(p[0]) for p in points]
    lats = [float(p[1]) for p in points]
    return (min(lats) + max(lats)) / 2.0, (min(lons) + max(lons)) / 2.0


def _periodo_from_pdf(path: Path) -> tuple[str, int]:
    """Periodo dalla prima pagina (anno più recente): fine del secondo semestre."""
    try:
        with pdfplumber.open(path) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception:
        text = ""
    dates = re.findall(r"al\s+(\d{1,2})/(\d{1,2})/(20\d{2})", text)
    if dates:
        d, m, y = dates[-1]
        return f"{int(m):02d}/{y}", int(y)
    m_y = re.search(r"\bAnno\s+(20\d{2})\b", text)
    if m_y:
        return m_y.group(1), int(m_y.group(1))
    return "", 0


def main() -> int:
    if not SRC_DIR.exists():
        print(f"[!] sorgente non trovata: {SRC_DIR}")
        return 1
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)
    castelli = fetch_castelli()
    if not castelli:
        return 1
    for old in PDF_OUT_DIR.glob(f"{PROVIDER_ID}_*.pdf"):
        old.unlink()

    features = []
    skipped = []
    for path in sorted(SRC_DIR.glob("*.pdf")):
        castello_label = path.stem.replace("_", " ").strip()
        poly = castelli.get(_normalize(castello_label))
        if not poly:
            skipped.append((path.name, f"polygon:{castello_label}"))
            continue
        periodo, year = _periodo_from_pdf(path)
        name = short_feature_name(
            PROVIDER_ID,
            castello_label,
            f"{PROVIDER_ID}|{path.as_posix()}",
        )
        shutil.copy2(path, PDF_OUT_DIR / f"{name}.pdf")
        lat, lon = _center(poly["geometry"])
        features.append({
            "type": "Feature",
            "geometry": poly["geometry"],
            "properties": {
                "name": name,
                "comune": poly["display_name"],
                "zona_label": f"Castello di {poly['display_name']}",
                "regione": "Repubblica di San Marino",
                "provincia": "",
                "provider": PROVIDER_ID,
                "provider_label": PROVIDER_LABEL,
                "provider_ato": PROVIDER_ATO,
                "periodo": periodo,
                "lat": lat,
                "lon": lon,
                "source_pdf": path.name,
                "source_year": year,
            },
        })

    OUT_FILE.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
        "_built_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    print(f"[write] {OUT_FILE.name}: {len(features)} features")
    if skipped:
        for name, reason in skipped:
            print(f"   ! {name}: {reason}")
    return 0 if features else 1


if __name__ == "__main__":
    sys.exit(main())
