"""
build_gaia.py
=============

Costruisce:
  - backend/data/mappa-qualita-gaia.json   (GeoJSON poligoni comunali)
  - backend/data/pdfs/gaia_<slug>.pdf       (PDF rappresentativo per comune)

Sorgente: backend/gaia_pdf/<comune>/<localita>.pdf
Gestore: GAIA S.p.A. (Toscana Nord — Lucca, Massa-Carrara, Pistoia)
ATO: Autorità Idrica Toscana — Conferenza Territoriale n.1 Toscana Nord

Un poligono comunale per cartella. Il PDF rappresentativo è la scheda del
capoluogo (o quella col nome più vicino al comune).

I poligoni comunali REALI vengono scaricati una sola volta da Overpass
(boundary admin_level=8 delle province di Lucca, Massa-Carrara e Pistoia) —
solo dati reali, nessuna tassellazione.
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
SRC_DIR = HERE / "gaia_pdf"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
POLY_CACHE_FILE = DATA_DIR / "gaia_polygons_cache.json"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-gaia.json"
ISTAT_GEOJSON = DATA_DIR / "istat_comuni_italia.geojson"

PROVIDER_INFO = {
    "label": "GAIA S.p.A.",
    "ato": "Autorità Idrica Toscana — Conferenza Territoriale n.1 Toscana Nord",
    "url": "https://www.gaia-spa.it/analisiweb_v2/",
}

_HEADERS = {"User-Agent": "AcquaMap-build/1.0 (acquamap-gaia)"}

# Comuni con denominazione OSM diversa dal nome cartella (fusioni 2014-2018).
_NAME_ALIAS = {
    "abetone": "abetone cutigliano",
    "casola di lunigiana": "casola in lunigiana",
    "castelnuovo garfagnana": "castelnuovo di garfagnana",
    "cutigliano": "abetone cutigliano",
    "san marcello pistoiese": "san marcello piteglio",
    "piteglio": "san marcello piteglio",
    "sillano": "sillano giuncugnano",
    "giuncugnano": "sillano giuncugnano",
    "vagli di sotto": "vagli sotto",
    "vergemoli": "fabbriche di vergemoli",
    "fabbriche di vallico": "fabbriche di vergemoli",
}


# ---------- utils ----------
def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", "", s.lower()).strip()


def load_cache() -> dict:
    if POLY_CACHE_FILE.exists():
        try:
            return json.loads(POLY_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(c: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POLY_CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


# ---------- discovery ----------
def _prefer_capoluogo(comune: str, pdfs: list[Path]) -> Path:
    """Scegli il PDF rappresentativo: prima 'capoluogo', poi quello col nome
    del comune, infine il primo in ordine alfabetico."""
    cap = [p for p in pdfs if "capoluogo" in p.stem.lower()]
    if cap:
        return sorted(cap)[0]
    cn = _normalize(comune)
    same = [p for p in pdfs if cn and cn in _normalize(p.stem)]
    if same:
        return sorted(same)[0]
    return sorted(pdfs)[0]


def discover_gaia() -> list[dict]:
    out: list[dict] = []
    if not SRC_DIR.exists():
        print(f"[!] cartella sorgente non trovata: {SRC_DIR}")
        return out
    for folder in sorted(SRC_DIR.iterdir()):
        if not folder.is_dir():
            continue
        pdfs = sorted(
            {p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"}
        )
        if not pdfs:
            continue
        comune = folder.name.replace("_", " ").strip()
        out.append({
            "slug": slugify(folder.name),
            "comune": comune.title(),
            "comune_geo": comune,
            "folder": folder,
            "primary_pdf": _prefer_capoluogo(comune, pdfs),
            "all_pdfs": pdfs,
        })
    return out


# ---------- geocoding (Overpass bulk) ----------
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


def _iter_points(coords):
    if not coords:
        return
    first = coords[0]
    if isinstance(first, (int, float)):
        yield coords
        return
    for item in coords:
        yield from _iter_points(item)


def _geometry_center(geom: dict) -> tuple[float, float]:
    points = list(_iter_points(geom.get("coordinates", [])))
    if not points:
        return 0.0, 0.0
    lons = [float(p[0]) for p in points]
    lats = [float(p[1]) for p in points]
    return (min(lats) + max(lats)) / 2.0, (min(lons) + max(lons)) / 2.0


def load_istat_polygons() -> dict[str, dict]:
    """Carica i confini comunali reali dal GeoJSON ISTAT locale."""
    if not ISTAT_GEOJSON.exists():
        return {}
    accepted_provinces = {"Lucca", "Massa-Carrara", "Pistoia"}
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    result: dict[str, dict] = {}
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if props.get("prov_name") not in accepted_provinces:
            continue
        name = props.get("name") or ""
        geom = feature.get("geometry")
        if not name or not geom:
            continue
        lat, lon = _geometry_center(geom)
        result[_normalize(name)] = {
            "geometry": geom,
            "lat": lat,
            "lon": lon,
            "display_name": name,
        }
    print(f"   [ISTAT] caricati {len(result)} poligoni comunali Toscana Nord")
    return result


def _match_polygon(comune: str, polygons: dict[str, dict]) -> dict | None:
    nk = _normalize(comune)
    nk = _NAME_ALIAS.get(nk, nk)
    info = polygons.get(nk)
    if info:
        return info
    for poly_key, poly_val in polygons.items():
        if nk and (nk in poly_key or poly_key in nk):
            return poly_val
    return None


def fetch_all_overpass() -> dict[str, dict]:
    """Scarica TUTTI i poligoni comunali (admin_level=8) delle province di
    Lucca, Massa-Carrara e Pistoia con UNA sola richiesta Overpass."""
    mirrors = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    query = (
        "[out:json][timeout:180];"
        'area["name"="Toscana"]["admin_level"="4"]->.t;'
        '(area["name"="Lucca"]["admin_level"="6"](area.t);'
        'area["name"="Massa-Carrara"]["admin_level"="6"](area.t);'
        'area["name"="Pistoia"]["admin_level"="6"](area.t);)->.prov;'
        'rel["boundary"="administrative"]["admin_level"="8"](area.prov);'
        "out geom;"
    )
    print("   [Overpass] scarica poligoni comunali Lucca+Massa-Carrara+Pistoia…")
    elements = None
    for url in mirrors:
        for attempt in range(2):
            try:
                r = requests.get(url, params={"data": query},
                                 headers=_HEADERS, timeout=200)
                if r.status_code in (429, 502, 503, 504):
                    print(f"   [Overpass] {url.split('/')[2]} → {r.status_code}, riprovo…")
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
        b = el.get("bounds", {})
        if b:
            lat = (b["minlat"] + b["maxlat"]) / 2.0
            lon = (b["minlon"] + b["maxlon"]) / 2.0
        else:
            lat = lon = 0.0
        result[_normalize(name)] = {
            "geometry": geom,
            "lat": float(lat),
            "lon": float(lon),
            "display_name": name,
        }
    print(f"   [Overpass] ottenuti {len(result)} poligoni")
    return result


# ---------- main ----------
def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] discovery cartelle comuni (gaia_pdf/)…")
    entries = discover_gaia()
    print(f"   totale: {len(entries)} comuni")

    print("[2/4] geocoding poligoni comunali…")
    cache = load_cache()
    stale = [k for k, v in cache.items() if v is None]
    for k in stale:
        del cache[k]

    missing = [e for e in entries if f"ga|{e['slug']}" not in cache]
    if missing:
        istat_map = load_istat_polygons()
        for e in list(missing):
            info = _match_polygon(e["comune_geo"], istat_map)
            if info:
                cache[f"ga|{e['slug']}"] = info
        missing = [e for e in entries if f"ga|{e['slug']}" not in cache]

    if missing:
        overpass_map = fetch_all_overpass()
        for e in missing:
            info = _match_polygon(e["comune_geo"], overpass_map)
            if info:
                cache[f"ga|{e['slug']}"] = info

    save_cache(cache)

    features = []
    skipped: list[str] = []
    for e in entries:
        info = cache.get(f"ga|{e['slug']}")
        if not info:
            skipped.append(e["comune"])
            print(f"   ! {e['comune']:35s}  GEOCODE FAIL")
            continue
        features.append({
            "type": "Feature",
            "geometry": info["geometry"],
            "properties": {
                "name": f"gaia_{e['slug']}",
                "comune": e["comune"],
                "zona_label": None,
                "regione": "Toscana",
                "provider": "toscana_gaia",
                "provider_label": PROVIDER_INFO["label"],
                "provider_ato": PROVIDER_INFO["ato"],
                "lat": info["lat"],
                "lon": info["lon"],
                "_src_pdf": str(e["primary_pdf"]),
            },
        })
    print(f"   poligoni totali: {len(features)}  /  skippati: {len(skipped)}")

    print("[3/4] copia PDF rappresentativi in data/pdfs/ …")
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
    fc = {
        "type": "FeatureCollection",
        "features": features,
        "_built_at": datetime.now(timezone.utc).isoformat(),
    }
    OUT_GEOJSON.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"   OK  {len(features)} features (poligoni comunali reali)")

    if skipped:
        print(f"\n[skipped] {len(skipped)} comuni senza poligono:")
        for com in skipped:
            print(f"   - {com}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
