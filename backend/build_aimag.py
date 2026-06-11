"""
Build AIMAG runtime data (area Modena/Mantova).

Creates:
  - backend/data/mappa-qualita-aimag.json
  - backend/data/pdfs/aimag_<slug>.pdf

Sources:
  - backend/aimag_pdf/<anno>_<Zona>_<n>_semestre_<anno>.pdf

Una scheda semestrale per zona di distribuzione; viene tenuto il semestre
più recente. "Cognento" è una frazione di Modena (poligono di Modena con
zona_label dedicata); "Revere" è confluito in Borgo Mantovano (MN, Lombardia).
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

SRC_DIR = HERE / "aimag_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-aimag.json"

PROVIDER_ID = "aimag"
PROVIDER_LABEL = "AIMAG S.p.A."
PROVIDER_ATO = "ATERSIR Emilia-Romagna / ATO Mantova"

MAX_FEATURE_NAME_LEN = 80

# Zona del portale -> (comuni ISTAT serviti, zona_label). La scheda "Cognento"
# è il potabilizzatore che serve 10 comuni della bassa modenese; "Revere"
# copre Borgo Mantovano e Borgo Carbonara (MN). Ogni comune servito diventa
# una feature che condivide lo stesso PDF.
ZONE_TO_COMUNI = {
    "campogalliano": (["Campogalliano", "Soliera", "Novi di Modena"],
                      "Rete Campogalliano-Soliera-Novi"),
    "carpi": (["Carpi"], "Rete di distribuzione"),
    "cognento": ([
        "Bastiglia", "Bomporto", "Camposanto", "Cavezzo",
        "Concordia sulla Secchia", "Medolla", "Mirandola",
        "San Felice sul Panaro", "San Possidonio", "San Prospero",
    ], "Acquedotto di Cognento"),
    "revere": (["Borgo Mantovano", "Borgocarbonara"], "Acquedotto di Revere"),
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
        if props.get("reg_name") not in ("Emilia-Romagna", "Lombardia") \
                or not feat.get("geometry"):
            continue
        name = props.get("name") or ""
        out[_normalize(name)] = {
            "name": name,
            "provincia": props.get("prov_name") or "",
            "regione": props.get("reg_name") or "",
            "geometry": feat["geometry"],
        }
    return out


def _periodo_from_pdf(path: Path) -> tuple[str, date | None]:
    try:
        with pdfplumber.open(path) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception:
        text = ""
    m = re.search(r"Periodo:\s*\d{1,2}/\d{1,2}/\d{4}\s*-\s*(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return f"{d.month:02d}/{d.year}", d
    return "", None


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

    # Tieni il semestre più recente per zona.
    grouped: dict[str, dict] = {}
    skipped = []
    for path in sorted(SRC_DIR.glob("*.pdf")):
        m = re.match(r"\d{4}_(.+?)_(\d)_semestre_(\d{4})$", path.stem)
        if not m:
            skipped.append((path.name, "nome file non riconosciuto"))
            continue
        zona_key = _normalize(m.group(1))
        periodo, d = _periodo_from_pdf(path)
        if not d:
            d = date(int(m.group(3)), 6 if m.group(2) == "1" else 12, 30)
            periodo = f"{d.month:02d}/{d.year}"
        if zona_key not in grouped or d > grouped[zona_key]["date"]:
            grouped[zona_key] = {"path": path, "date": d, "periodo": periodo}

    features = []
    for zona_key, e in sorted(grouped.items()):
        mapping = ZONE_TO_COMUNI.get(zona_key)
        if not mapping:
            skipped.append((e["path"].name, f"zona sconosciuta: {zona_key}"))
            continue
        comuni, zona_label = mapping
        for comune in comuni:
            poly = polygons.get(_normalize(comune))
            if not poly:
                skipped.append((e["path"].name, f"polygon:{comune}"))
                continue
            # Il nome contiene solo il comune (il parser lo ricava dallo stem).
            name = short_feature_name(
                PROVIDER_ID, comune, f"{PROVIDER_ID}|{zona_key}|{comune}")
            shutil.copy2(e["path"], PDF_OUT_DIR / f"{name}.pdf")
            lat, lon = _center(poly["geometry"])
            features.append({
                "type": "Feature",
                "geometry": poly["geometry"],
                "properties": {
                    "name": name,
                    "comune": poly["name"],
                    "zona_label": zona_label,
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
