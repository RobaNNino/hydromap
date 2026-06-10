"""
build_basilicata.py
===================

Costruisce:
  - backend/data/mappa-qualita-basilicata.json   (GeoJSON poligoni comunali)
  - backend/data/pdfs/basilicata_al_<slug>.pdf   (PDF rappresentativi)

Sorgente: backend/acquedottolucano_pdf/<Comune>/
  - <Nome>.pdf         → referto Lab 1843 (Acquedotto Lucano interno)
  - <Nome>_SCA.pdf     → referto Lab 0648 (SCA esterno, chimico pesante)
  - NN_NNNN_NN-signed.pdf  → altro referto SCA firmato digitalmente

Gestore: Acquedotto Lucano S.p.A.
ATO: EGRIB — Ente di Governo del Rischio Idrogeologico e dei Rifiuti in Basilicata
Un poligono comunale per folder/comune.  PDF rappresentativo = Lab interno AL
(preferito perché contiene la riga «Comune: NOME» e parametri di base).
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
SRC_DIR = HERE / "acquedottolucano_pdf"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
POLY_CACHE_FILE = DATA_DIR / "basilicata_polygons_cache.json"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-basilicata.json"

PROVIDER_INFO = {
    "label": "Acquedotto Lucano S.p.A.",
    "ato": "EGRIB — Ente di Governo del Rischio Idrogeologico e dei Rifiuti in Basilicata",
    "url": "https://www.acquedottolucano.it/qualita-acqua",
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
    POLY_CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


# ---------- discovery ----------
_SCA_PAT = re.compile(r"_SCA(?:\.pdf)?$|-signed(?:\.pdf)?$|^\d{2}_\d{3,4}_\d+-signed", re.IGNORECASE)


def _is_sca(name: str) -> bool:
    """True se il file è un referto SCA o -signed (non il Lab AL interno)."""
    return bool(_SCA_PAT.search(name))


def _prefer_abitato(pdfs: list[Path]) -> Path:
    """Scegli il PDF più rappresentativo tra quelli non-SCA:
    1. Contiene 'abitato' nel nome (zona principale del comune).
    2. Altrimenti il primo in ordine alfabetico.
    """
    non_sca = [p for p in pdfs if not _is_sca(p.name)]
    if not non_sca:
        non_sca = sorted(pdfs)  # fallback: qualsiasi file
    abitato = [p for p in non_sca if "abitato" in p.stem.lower()]
    if abitato:
        return sorted(abitato)[0]
    return sorted(non_sca)[0]


def discover_basilicata() -> list[dict]:
    """Un entry per cartella/comune in acquedottolucano_pdf/."""
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
        # Label/nome comune: sostituisci _ con spazio, rimpiazza " - " con " — "
        label = folder.name.replace("_", " ").replace(" - ", " — ").strip()
        comune_geo = re.split(r"\s+[—-]\s+", label)[0].strip()
        slug = slugify(folder.name)
        primary = _prefer_abitato(pdfs)
        out.append({
            "slug": slug,
            "label": label,
            "comune_geo": comune_geo,
            "folder": folder,
            "primary_pdf": primary,
            "all_pdfs": pdfs,
        })
    return out


# ---------- geocoding ----------
_HEADERS = {"User-Agent": "AcquaMap-build/1.0 (acquamap-basilicata)"}

# ---- Overpass bulk download (one request for all Basilicata comuni) ----

def _normalize(s: str) -> str:
    """Lowercase, strip accents, remove apostrophes for fuzzy matching."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", "", s.lower()).strip()


def _pt_key(p: dict) -> tuple:
    return (round(p["lat"], 7), round(p["lon"], 7))


def _assemble_rings(ways: list[list[dict]]) -> list[list[list[float]]]:
    """Assemble a list of ways (each a list of {lat, lon}) into closed rings.

    Greedily connects ways end-to-end until a ring closes, then starts a new
    ring with the remaining ways. Returns rings as GeoJSON coordinate lists
    [[lon, lat], …] (closed).
    """
    remaining = [list(w) for w in ways if w and len(w) >= 2]
    rings: list[list[list[float]]] = []

    while remaining:
        chain = remaining.pop(0)
        # Extend the chain until it closes back on its start.
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
        # Close the ring if needed.
        if _pt_key(chain[0]) != _pt_key(chain[-1]):
            chain.append(chain[0])
        if len(chain) >= 4:
            rings.append([[p["lon"], p["lat"]] for p in chain])

    return rings


def _relation_to_geojson(members: list[dict]) -> dict | None:
    """Convert Overpass relation members (with inline geometry) to GeoJSON Polygon/MultiPolygon."""
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
        return {
            "type": "Polygon",
            "coordinates": [outer_rings[0]] + inner_rings,
        }
    # MultiPolygon: assign each inner ring to the outer ring containing it.
    polys = [[ring] for ring in outer_rings]
    for ir in inner_rings:
        # Use the inner ring's first point to find its containing outer ring.
        px, py = ir[0]
        for idx, oring in enumerate(outer_rings):
            if _point_in_ring(px, py, oring):
                polys[idx].append(ir)
                break
        else:
            polys[0].append(ir)
    return {
        "type": "MultiPolygon",
        "coordinates": polys,
    }


def _point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test (ring is [[lon, lat], …])."""
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


def fetch_all_overpass() -> dict[str, dict]:
    """Download ALL Basilicata municipality polygons via ONE Overpass API call.

    Returns a dict mapping normalized comune name → polygon info dict.
    """
    _OVERPASS_MIRRORS = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    # `out geom;` returns tags AND member geometry (adding `tags` drops members).
    query = (
        "[out:json][timeout:180];"
        'area["name"="Basilicata"]["boundary"="administrative"]->.reg;'
        'rel["boundary"="administrative"]["admin_level"="8"](area.reg);'
        "out geom;"
    )

    print("   [Overpass] scarica poligoni Basilicata (query unica)…")
    elements = None
    for url in _OVERPASS_MIRRORS:
        for attempt in range(2):
            try:
                r = requests.get(
                    url,
                    params={"data": query},
                    headers=_HEADERS,
                    timeout=200,
                )
                if r.status_code in (429, 504, 502, 503):
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
        members = el.get("members", [])
        geom = _relation_to_geojson(members)
        if not geom:
            continue
        # Center from bounds (Overpass `out geom` doesn't include `center`).
        b = el.get("bounds", {})
        if b:
            lat = (b["minlat"] + b["maxlat"]) / 2.0
            lon = (b["minlon"] + b["maxlon"]) / 2.0
        else:
            lat = lon = 0.0
        key = _normalize(name)
        result[key] = {
            "geometry": geom,
            "lat": float(lat),
            "lon": float(lon),
            "display_name": name,
        }

    print(f"   [Overpass] ottenuti {len(result)} poligoni")
    return result


# ---- Nominatim fallback for individual lookups ----

def fetch_polygon_nominatim(comune: str) -> dict | None:
    """Fallback: individual Nominatim query with 429 backoff."""
    queries = [
        f"{comune}, Basilicata, Italia",
        f"{comune}, Italia",
    ]
    for q in queries:
        for attempt in range(3):
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
                if r.status_code == 429:
                    wait = 60 * (attempt + 1)
                    print(f"   [429] rate limited, attendo {wait}s…")
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    break
                arr = r.json()
                if not arr:
                    break
                ok_types = {"administrative", "city", "town", "village", "municipality", "hamlet"}
                for it in arr:
                    geom = it.get("geojson")
                    if not geom:
                        continue
                    if (geom.get("type") or "") in ("Point", "LineString", "MultiLineString"):
                        continue
                    t = (it.get("type") or "").lower()
                    cls = (it.get("class") or "").lower()
                    if cls not in ("boundary", "place") and t not in ok_types:
                        continue
                    return {
                        "geometry": geom,
                        "lat": float(it["lat"]),
                        "lon": float(it["lon"]),
                        "display_name": it.get("display_name", ""),
                    }
                break
            except requests.RequestException:
                time.sleep(3)
    return None


# ---------- main ----------
def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] discovery cartelle comuni (acquedottolucano_pdf/)…")
    entries = discover_basilicata()
    print(f"   totale: {len(entries)} comuni")

    print("[2/4] geocoding poligoni comunali…")
    cache = load_cache()

    # Clear stale None entries so we retry them.
    stale = [k for k, v in cache.items() if v is None]
    for k in stale:
        del cache[k]
    if stale:
        print(f"   rimossi {len(stale)} fallimenti precedenti dalla cache")

    # Try Overpass bulk download first (one API call for all comuni).
    missing_entries = [e for e in entries if f"al|{e['slug']}" not in cache]
    overpass_map: dict[str, dict] = {}
    if missing_entries:
        overpass_map = fetch_all_overpass()
        # Fix folder-name typos / OSM naming differences.
        _NAME_ALIAS = {
            "bargiano": "baragiano",                 # folder typo
            "terranova del pollino": "terranova di pollino",  # OSM uses "di"
        }
        # Match Overpass results to entries by normalized name.
        for e in missing_entries:
            key = f"al|{e['slug']}"
            nk = _normalize(e["comune_geo"])
            nk = _NAME_ALIAS.get(nk, nk)
            info = overpass_map.get(nk)
            if not info:
                # Try alternate normalizations (e.g. "san chirico" → "s. chirico")
                for ovkey, ovval in overpass_map.items():
                    if nk in ovkey or ovkey in nk:
                        info = ovval
                        break
            if info:
                cache[key] = info

    save_cache(cache)

    # Nominatim fallback for entries still missing after Overpass.
    still_missing = [e for e in entries if cache.get(f"al|{e['slug']}") is None
                     and f"al|{e['slug']}" not in cache]
    # Also check for keys not yet in cache at all.
    still_missing = [e for e in entries if f"al|{e['slug']}" not in cache]
    if still_missing:
        print(f"   [Nominatim fallback] {len(still_missing)} comuni ancora senza poligono…")
        for i, e in enumerate(still_missing, 1):
            key = f"al|{e['slug']}"
            info = fetch_polygon_nominatim(e["comune_geo"])
            cache[key] = info
            time.sleep(1.5)
            if i % 10 == 0:
                save_cache(cache)
                print(f"   …{i}/{len(still_missing)} nominatim")
        save_cache(cache)

    features = []
    skipped: list[str] = []
    for e in entries:
        key = f"al|{e['slug']}"
        info = cache.get(key)
        if not info:
            skipped.append(e["label"])
            print(f"   ! {e['label']:40s}  GEOCODE FAIL")
            continue
        feat = {
            "type": "Feature",
            "geometry": info["geometry"],
            "properties": {
                "name": f"basilicata_al_{e['slug']}",
                "comune": e["label"],
                "zona_label": None,
                "regione": "Basilicata",
                "provider": "basilicata_al",
                "provider_label": PROVIDER_INFO["label"],
                "provider_ato": PROVIDER_INFO["ato"],
                "lat": info["lat"],
                "lon": info["lon"],
                "_src_pdf": str(e["primary_pdf"]),
            },
        }
        features.append(feat)
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
