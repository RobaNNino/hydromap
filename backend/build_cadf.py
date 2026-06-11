"""
Build CADF runtime data (basso ferrarese, 11 comuni del Delta del Po).

Creates:
  - backend/data/mappa-qualita-cadf.json
  - backend/data/pdfs/cadf_<comune>.pdf

Sources:
  - backend/cadf_pdf/cadf_<comune-slug>[-2].pdf   (una scheda per comune)

Il comune è nello slug del nome file; il periodo nel testo
("Periodo: gennaio, febbraio e marzo 2026" → ultimo mese).
"""
from __future__ import annotations

import json
import hashlib
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
ISTAT_GEOJSON = DATA_DIR / "istat_comuni_italia.geojson"

SRC_DIR = HERE / "cadf_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-cadf.json"

PROVIDER_ID = "cadf"
PROVIDER_LABEL = "CADF S.p.A."
PROVIDER_ATO = "ATERSIR - Emilia-Romagna (basso ferrarese)"

MAX_FEATURE_NAME_LEN = 80

MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}


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


def load_polygons() -> dict[str, dict]:
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        if props.get("reg_name") != "Emilia-Romagna" or not feat.get("geometry"):
            continue
        name = props.get("name") or ""
        out[_normalize(name)] = {
            "name": name,
            "provincia": props.get("prov_name") or "",
            "regione": "Emilia-Romagna",
            "geometry": feat["geometry"],
        }
    return out


def _periodo_from_pdf(path: Path) -> tuple[str, int]:
    try:
        with pdfplumber.open(path) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception:
        text = ""
    m = re.search(r"Periodo:\s*([^\n]+?)\s+(20\d{2})", text, re.I)
    if m:
        months = [MONTHS_IT[w] for w in re.findall(
            r"|".join(MONTHS_IT), m.group(1).lower())]
        year = int(m.group(2))
        if months:
            return f"{max(months):02d}/{year}", year
        return str(year), year
    return "", 0


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
    polygons = load_polygons()
    for old in PDF_OUT_DIR.glob(f"{PROVIDER_ID}_*.pdf"):
        old.unlink()

    features = []
    skipped = []
    for path in sorted(SRC_DIR.glob("*.pdf")):
        slug = re.sub(r"^cadf_", "", path.stem)
        slug = re.sub(r"-\d+$", "", slug)
        comune_label = slug.replace("-", " ").title()
        poly = polygons.get(_normalize(comune_label))
        if not poly:
            skipped.append((path.name, f"polygon:{comune_label}"))
            continue
        periodo, year = _periodo_from_pdf(path)
        name = short_feature_name(PROVIDER_ID, comune_label, f"{PROVIDER_ID}|{slug}")
        shutil.copy2(path, PDF_OUT_DIR / f"{name}.pdf")
        lat, lon = _center(poly["geometry"])
        features.append({
            "type": "Feature",
            "geometry": poly["geometry"],
            "properties": {
                "name": name,
                "comune": poly["name"],
                "zona_label": "Rete di distribuzione",
                "regione": poly["regione"],
                "provincia": poly["provincia"],
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
    for name, reason in skipped:
        print(f"   ! {name}: {reason}")
    return 0 if features else 1


if __name__ == "__main__":
    sys.exit(main())
