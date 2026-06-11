"""
Build CIIP runtime data (ATO 5 Marche Sud — Ascoli Piceno e Fermo).

Creates:
  - backend/data/mappa-qualita-ciip.json
  - backend/data/pdfs/marche_ciip_<slug>.pdf

Sources:
  - backend/ciip_pdf/utenze_*.pdf      (analisi per utenza, una per comune/via)
  - backend/ciip_pdf/sorgenti_*.pdf    (NON mappati: nessun comune associato)
  - backend/ciip_pdf/pozzi_*.pdf       (NON mappati: nessun comune associato)

Le utenze portano comune/via nel testo ("Parametri: comune: X / via: Y /
civico: Z"): ogni utenza diventa una feature col poligono comunale ISTAT.
Più utenze nello stesso comune = più feature sovrapposte (il frontend ha il
selettore di disambiguazione).
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

SRC_DIR = HERE / "ciip_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-ciip.json"

PROVIDER_ID = "marche_ciip"
PROVIDER_LABEL = "CIIP S.p.A."
PROVIDER_ATO = "ATO 5 Marche Sud - Ascoli Piceno e Fermo"

MIN_YEAR = 2024
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


def _soft_title(s: str) -> str:
    """Title-case morbido per etichette tutte maiuscole (C.DA → C.da)."""
    out = s.title()
    out = re.sub(r"\b(Di|Del|Della|Delle|Dei|Degli|Da|De|E)\b", lambda m: m.group(1).lower(), out)
    return out


def load_polygons() -> dict[str, dict]:
    """Poligoni comunali ISTAT di Marche + Abruzzo (CIIP serve AP/FM e confini)."""
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        if props.get("reg_name") not in ("Marche", "Abruzzo") or not feat.get("geometry"):
            continue
        name = props.get("name") or ""
        out[_normalize(name)] = {
            "name": name,
            "provincia": props.get("prov_name") or "",
            "regione": props.get("reg_name") or "",
            "geometry": feat["geometry"],
        }
    return out


def _first_page_text(path: Path) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            return pdf.pages[0].extract_text() or ""
    except Exception:
        return ""


def discover_utenze(polygons: dict[str, dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    grouped: dict[str, dict] = {}
    skipped: list[tuple[str, str]] = []
    for path in sorted(SRC_DIR.glob("utenze_*.pdf")):
        text = _first_page_text(path)
        m_com = re.search(r"comune:\s*([^/\n]+)", text, re.I)
        if not m_com:
            skipped.append((path.name, "comune non trovato nel testo"))
            continue
        comune_raw = _clean(m_com.group(1))
        m_via = re.search(r"via:\s*([^/\n]+)", text, re.I)
        m_civ = re.search(r"civico:\s*([^/\n]+)", text, re.I)
        via = _soft_title(_clean(m_via.group(1))) if m_via else ""
        civ = _clean(m_civ.group(1)) if m_civ else ""
        zona = via or comune_raw.title()
        if civ and civ.upper() not in {"", "0", "0000", "SNC"}:
            zona = f"{zona}, {civ}"
        m_date = re.search(r"Data prelievo:\s*(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if not m_date:
            skipped.append((path.name, "data prelievo non trovata"))
            continue
        d = date(int(m_date.group(3)), int(m_date.group(2)), int(m_date.group(1)))
        if d.year < MIN_YEAR:
            skipped.append((path.name, f"troppo vecchio: {d.isoformat()}"))
            continue
        if _normalize(comune_raw) not in polygons:
            skipped.append((path.name, f"polygon:{comune_raw}"))
            continue
        key = slugify(f"{comune_raw}_{via}")
        item = {
            "path": path,
            "comune": comune_raw,
            "zona": zona,
            "date": d,
            "periodo": f"{d.day:02d}/{d.month:02d}/{d.year:04d}",
        }
        if key not in grouped or d > grouped[key]["date"]:
            grouped[key] = item
    return sorted(grouped.values(), key=lambda x: (x["comune"], x["zona"])), skipped


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

    entries, skipped = discover_utenze(polygons)
    n_src = len(list(SRC_DIR.glob("utenze_*.pdf")))
    n_extra = len(list(SRC_DIR.glob("sorgenti_*.pdf"))) + len(list(SRC_DIR.glob("pozzi_*.pdf")))
    print(f"[ciip] utenze selezionate: {len(entries)} / {n_src} "
          f"(+{n_extra} sorgenti/pozzi non mappabili, ignorati)")

    features = []
    for e in entries:
        poly = polygons[_normalize(e["comune"])]
        name = short_feature_name(
            PROVIDER_ID,
            f"{e['comune']}_{e['zona']}",
            f"{PROVIDER_ID}|{e['path'].as_posix()}",
        )
        shutil.copy2(e["path"], PDF_OUT_DIR / f"{name}.pdf")
        lat, lon = _center(poly["geometry"])
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
        "_min_year": MIN_YEAR,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"[write] {OUT_FILE.name}: {len(features)} features")
    if skipped:
        print(f"[!] skipped {len(skipped)}:")
        for name, reason in skipped[:40]:
            print(f"   - {name}: {reason}")
    return 0 if features else 1


if __name__ == "__main__":
    sys.exit(main())
