"""
Build AS Comuni Riuniti runtime data (Montecopiolo, RN).

Creates:
  - backend/data/mappa-qualita-comuniriuniti.json
  - backend/data/pdfs/comuniriuniti_<slug>.pdf

Sources:
  - backend/as_comuniriuniti_pdf/*.pdf   (rapporti di prova CSA)

L'Azienda Speciale Comuni Riuniti pubblica i rapporti di prova dei punti di
campionamento di Montecopiolo. Per ciascun punto (dalla "Descrizione
campione") viene tenuto il rapporto più recente.
"""
from __future__ import annotations

import json
import hashlib
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
ISTAT_GEOJSON = DATA_DIR / "istat_comuni_italia.geojson"

SRC_DIR = HERE / "as_comuniriuniti_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-comuniriuniti.json"

PROVIDER_ID = "comuniriuniti"
PROVIDER_LABEL = "AS Comuni Riuniti"
PROVIDER_ATO = "Comune di Montecopiolo (RN)"
COMUNE = "Montecopiolo"

MAX_FEATURE_NAME_LEN = 80


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


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s.lower())).strip()


def load_comune_polygon() -> dict | None:
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        if _normalize(props.get("name") or "") == _normalize(COMUNE) \
                and feat.get("geometry"):
            return {
                "name": props.get("name"),
                "provincia": props.get("prov_name") or "",
                "regione": props.get("reg_name") or "",
                "geometry": feat["geometry"],
            }
    return None


def _first_page_text(path: Path) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            return pdf.pages[0].extract_text() or ""
    except Exception:
        return ""


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


def main() -> int:
    if not SRC_DIR.exists():
        print(f"[!] sorgente non trovata: {SRC_DIR}")
        return 1
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)
    poly = load_comune_polygon()
    if not poly:
        print(f"[!] poligono di {COMUNE} non trovato nell'ISTAT geojson")
        return 1
    for old in PDF_OUT_DIR.glob(f"{PROVIDER_ID}_*.pdf"):
        old.unlink()

    grouped: dict[str, dict] = {}
    skipped = []
    for path in sorted(SRC_DIR.glob("*.pdf")):
        text = _first_page_text(path)
        m = re.search(r"Descrizione campione:\s*([^\n]+)", text)
        zona = _clean(re.sub(r"^Acqua\s+", "", m.group(1))) if m else path.stem
        m = re.search(r"Data di campionamento:\s*(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if not m:
            skipped.append((path.name, "data campionamento non trovata"))
            continue
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        key = slugify(zona)
        item = {
            "path": path, "zona": zona, "date": d,
            "periodo": f"{d.day:02d}/{d.month:02d}/{d.year:04d}",
        }
        if key not in grouped or d > grouped[key]["date"]:
            grouped[key] = item

    features = []
    lat, lon = _center(poly["geometry"])
    for key, e in sorted(grouped.items()):
        name = short_feature_name(PROVIDER_ID, e["zona"], f"{PROVIDER_ID}|{key}")
        shutil.copy2(e["path"], PDF_OUT_DIR / f"{name}.pdf")
        features.append({
            "type": "Feature",
            "geometry": poly["geometry"],
            "properties": {
                "name": name,
                "comune": poly["name"],
                "zona_label": e["zona"],
                "regione": poly["regione"],
                "provincia": poly["provincia"],
                "provider": PROVIDER_ID,
                "provider_label": PROVIDER_LABEL,
                "provider_ato": PROVIDER_ATO,
                "periodo": e["periodo"],
                "lat": lat,
                "lon": lon,
                "source_pdf": e["path"].name,
                "source_year": e["date"].year,
            },
        })

    OUT_FILE.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
        "_built_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    print(f"[write] {OUT_FILE.name}: {len(features)} features")
    for name, reason in skipped:
        print(f"   ! {name}: {reason}")
    return 0 if features else 1


if __name__ == "__main__":
    sys.exit(main())
