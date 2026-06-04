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
ACEA_SRC_DIR = HERE / "data" / "source_acea_molise"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
POLY_CACHE_FILE = DATA_DIR / "molise_polygons_cache.json"
REGION_CACHE_FILE = DATA_DIR / "molise_region_boundary.json"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-molise.json"

# Mappa ufficiale Acea Molise (Termoli): 3 aree qualità reali con rapporti
# di prova testuali (parametri estraibili). Sorgente:
#   https://www.aceamolise.a-acqua.it/qualita-acqua
ACEA_MAP_JSON = (
    "https://www.aceamolise.a-acqua.it/content/dam/acea-molise/json/"
    "ACEA_MOLISE_AREE_QUALITA_18112025.json"
)
ACEA_PDF_BASE = (
    "https://www.aceamolise.a-acqua.it/content/dam/acea-molise/pdf/"
    "mappe-qualita/"
)

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


def fetch_region_boundary():
    """Confine amministrativo della regione Molise (poligono), con cache."""
    if REGION_CACHE_FILE.exists():
        try:
            return json.loads(REGION_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": "Molise, Italia", "format": "json",
                    "polygon_geojson": 1, "limit": 3, "countrycodes": "it"},
            headers=_HEADERS, timeout=30,
        )
        for it in r.json():
            if (it.get("class") == "boundary"
                    and it.get("type") == "administrative"
                    and it.get("geojson", {}).get("type") in
                    ("Polygon", "MultiPolygon")):
                geom = it["geojson"]
                REGION_CACHE_FILE.write_text(
                    json.dumps(geom, ensure_ascii=False), encoding="utf-8")
                return geom
    except requests.RequestException:
        pass
    return None


def fetch_acea_areas() -> list[dict]:
    """
    Scarica la mappa ufficiale Acea Molise (aree qualità di Termoli) e i
    relativi rapporti di prova PDF (testuali, parametri estraibili).
    Ritorna [{name, slug, geometry, lat, lon, pdf}].
    """
    from shapely.geometry import shape
    ACEA_SRC_DIR.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(ACEA_MAP_JSON, headers=_HEADERS, timeout=40)
        r.raise_for_status()
        fc = r.json()
    except Exception as exc:
        print(f"   ! Acea map fetch fail: {exc}")
        return []

    out: list[dict] = []
    for feat in fc.get("features", []):
        geom = feat.get("geometry")
        name = (feat.get("properties") or {}).get("name")
        if not geom or not name:
            continue
        slug = slugify(name)
        # centroide reale del poligono
        try:
            c = shape(geom).centroid
            lon, lat = float(c.x), float(c.y)
        except Exception:
            continue
        # scarica il PDF rappresentativo dell'area
        from urllib.parse import quote
        pdf_url = ACEA_PDF_BASE + quote(name) + ".pdf"
        pdf_path = ACEA_SRC_DIR / f"{name}.pdf"
        if not pdf_path.exists():
            try:
                pr = requests.get(pdf_url, headers=_HEADERS, timeout=40)
                pr.raise_for_status()
                pdf_path.write_bytes(pr.content)
            except Exception as exc:
                print(f"   ! Acea PDF fail {name}: {exc}")
                pdf_path = None
        out.append({"name": name, "slug": slug, "geometry": geom,
                    "lat": lat, "lon": lon, "pdf": pdf_path})
    return out


# ---------- main ----------
def main() -> int:
    from shapely.geometry import shape, mapping, Point, MultiPoint
    from shapely.ops import voronoi_diagram, unary_union

    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/5] discovery PDF Molise (GRIM)…")
    entries = discover_molise()
    print(f"   totale: {len(entries)} comuni GRIM")

    print("[2/5] mappa ufficiale Acea Molise (Termoli)…")
    acea_areas = fetch_acea_areas()
    print(f"   aree qualità Acea: {len(acea_areas)}")

    print("[3/5] geocoding centroidi comuni (Nominatim, ~1s/comune)…")
    cache = load_cache()
    # Ogni "seed" è un punto-dato con un PDF reale associato.
    seeds: list[dict] = []
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
        seeds.append({
            "name": f"molise_acea_{slugify(comune)}",
            "comune": comune,
            "zona_label": None,
            "provincia_acr": prov,
            "lat": info["lat"],
            "lon": info["lon"],
            "pdf": e["pdf"],
        })
    save_cache(cache)

    # Seeds delle 3 aree Acea (Termoli) — dati reali, parametri estraibili.
    for a in acea_areas:
        seeds.append({
            "name": f"molise_termoli_{a['slug']}",
            "comune": "Termoli",
            "zona_label": a["name"],
            "provincia_acr": "CB",
            "lat": a["lat"],
            "lon": a["lon"],
            "pdf": a["pdf"],
        })

    print(f"   seed totali (punti-dato): {len(seeds)}  /  "
          f"skippati: {len(skipped)}")

    print("[4/5] tassellazione Voronoi sull'intera regione Molise…")
    region_geom = fetch_region_boundary()
    if not region_geom:
        print("   ! confine regionale non disponibile: uso inviluppo dei seed")
    bnd = shape(region_geom) if region_geom else None
    pts = [Point(s["lon"], s["lat"]) for s in seeds]
    mp = MultiPoint(pts)
    if bnd is None:
        bnd = mp.convex_hull.buffer(0.1)
    try:
        regions = list(voronoi_diagram(mp, envelope=bnd).geoms)
    except Exception as exc:
        print(f"   ! voronoi fail: {exc}")
        regions = []

    features = []
    for s, pt in zip(seeds, pts):
        cell = next((reg for reg in regions if reg.covers(pt)), None)
        if cell is None:
            cell = pt.buffer(0.03)
        clipped = cell.intersection(bnd)
        if clipped.is_empty or clipped.area == 0:
            clipped = pt.buffer(0.02).intersection(bnd)
        if clipped.is_empty:
            clipped = pt.buffer(0.02)
        if clipped.geom_type == "GeometryCollection":
            polys = [g for g in clipped.geoms
                     if g.geom_type in ("Polygon", "MultiPolygon")]
            clipped = unary_union(polys) if polys else pt.buffer(0.02)
        feat = {
            "type": "Feature",
            "geometry": mapping(clipped),
            "properties": {
                "name": s["name"],
                "comune": s["comune"],
                "zona_label": s["zona_label"],
                "provincia_acr": s["provincia_acr"],
                "regione": "Molise",
                "provider": "molise_acea",
                "provider_label": PROVIDER_INFO["acea"]["label"],
                "provider_ato": PROVIDER_INFO["acea"]["ato"],
                "lat": s["lat"],
                "lon": s["lon"],
                "_src_pdf": str(s["pdf"]) if s.get("pdf") else None,
            },
        }
        features.append(feat)

    print("[5/5] copia PDF in data/pdfs/ e scrive geojson…")
    for f in features:
        src = f["properties"].pop("_src_pdf", None)
        if not src:
            continue
        dest = PDF_OUT_DIR / (f["properties"]["name"] + ".pdf")
        try:
            shutil.copy2(src, dest)
        except Exception as exc:
            print(f"   ! copy fail {dest.name}: {exc}")

    fc = {"type": "FeatureCollection", "features": features,
          "_built_at": datetime.now(timezone.utc).isoformat()}
    OUT_GEOJSON.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"   OK  {len(features)} features (regione interamente coperta)")

    if skipped:
        print(f"\n[skipped] {len(skipped)} comuni senza centroide:")
        for com in skipped:
            print(f"   - {com}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
