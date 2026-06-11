"""
Build Sorgeaqua runtime data (Crevalcore, Finale Emilia, Nonantola, Ravarino,
Sant'Agata Bolognese — confine Modena/Bologna).

Creates:
  - backend/data/mappa-qualita-sorgeaqua.json
  - backend/data/pdfs/sorgeaqua_<slug>.pdf

Sources:
  - backend/sorgeaqua_pdf/<anno>_<Comune>_(anno|N_semestre)_<anno>.pdf

Per ciascun comune viene tenuto il referto più recente. I PDF aggregati
"territorio_Sorgeaqua" (valori medi su tutta la rete) e la legenda
"Parametri_analitici" non hanno un comune e restano fuori mappa.
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

SRC_DIR = HERE / "sorgeaqua_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-sorgeaqua.json"

PROVIDER_ID = "sorgeaqua"
PROVIDER_LABEL = "SorgeAqua S.r.l."
PROVIDER_ATO = "ATERSIR - Emilia-Romagna (Modena/Bologna)"

MAX_FEATURE_NAME_LEN = 80

# Grafie abbreviate nei PDF rispetto ai nomi ISTAT.
ALIASES = {
    "s agata bolognese": "sant agata bolognese",
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


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


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


def _comune_and_period(path: Path) -> tuple[str, str, date | None]:
    try:
        with pdfplumber.open(path) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception:
        text = ""
    m = re.search(r"DISTRIBUITA NEL COMUNE DI\s+([^\n]+)", text, re.I)
    comune = _clean(m.group(1)).title() if m else ""
    m = re.search(r"Periodo:\s*dal\s+\d{1,2}/\d{1,2}/\d{4}\s+al\s+(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return comune, f"{d.month:02d}/{d.year}", d
    m = re.search(r"\b(20\d{2})\b", path.stem)
    if m:
        y = int(m.group(1))
        return comune, str(y), date(y, 12, 31)
    return comune, "", None


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

    grouped: dict[str, dict] = {}
    skipped = []
    for path in sorted(SRC_DIR.glob("*.pdf")):
        if "territorio" in path.stem.lower() or "parametri" in path.stem.lower():
            skipped.append((path.name, "aggregato/legenda, nessun comune"))
            continue
        comune, periodo, d = _comune_and_period(path)
        if not comune or not d:
            skipped.append((path.name, "comune o periodo non trovato"))
            continue
        key = _normalize(comune)
        key = ALIASES.get(key, key)
        if key not in grouped or d > grouped[key]["date"]:
            grouped[key] = {"path": path, "comune": comune, "date": d, "periodo": periodo}

    features = []
    for key, e in sorted(grouped.items()):
        poly = polygons.get(key)
        if not poly:
            skipped.append((e["path"].name, f"polygon:{e['comune']}"))
            continue
        name = short_feature_name(PROVIDER_ID, e["comune"], f"{PROVIDER_ID}|{key}")
        shutil.copy2(e["path"], PDF_OUT_DIR / f"{name}.pdf")
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
