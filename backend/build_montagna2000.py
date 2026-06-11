"""
Build Montagna 2000 runtime data (Appennino parmense, Emilia-Romagna).

Creates:
  - backend/data/mappa-qualita-montagna2000.json
  - backend/data/pdfs/montagna2000_<slug>.pdf

Sources:
  - backend/montagna2000_pdf/*.pdf   (un referto per acquedotto, codice NG2*)

Comune e acquedotto vengono letti dal testo ("Comune/area: X" + titolo
"Acq. <nome> campione del <data>"). Ogni acquedotto diventa una feature col
poligono comunale ISTAT; più acquedotti nello stesso comune = più feature
sovrapposte (il frontend ha il selettore). Per ciascun codice acquedotto
viene tenuto solo il campione più recente.
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

SRC_DIR = HERE / "montagna2000_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-montagna2000.json"

PROVIDER_ID = "montagna2000"
PROVIDER_LABEL = "Montagna 2000 S.p.A."
PROVIDER_ATO = "ATERSIR - Emilia-Romagna (Appennino parmense)"

MAX_FEATURE_NAME_LEN = 80

ALIASES: dict[str, str] = {
    "fornovo": "fornovo di taro",
    "varano melegari": "varano de melegari",
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
    """Poligoni comunali ISTAT: Emilia-Romagna + regioni di confine."""
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        if props.get("reg_name") not in ("Emilia-Romagna", "Liguria", "Toscana") \
                or not feat.get("geometry"):
            continue
        name = props.get("name") or ""
        key = _normalize(name)
        # In caso di omonimie tra regioni preferisci l'Emilia-Romagna.
        if key in out and props.get("reg_name") != "Emilia-Romagna":
            continue
        out[key] = {
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


def discover(polygons: dict[str, dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    grouped: dict[str, dict] = {}
    skipped: list[tuple[str, str]] = []
    # Primo passaggio: impara prefisso codice (NG2XXX) -> comune dagli altri
    # referti, per i PDF in cui "Comune/area:" è vuoto.
    prefix_to_comune: dict[str, str] = {}
    pages: list[tuple[Path, str]] = []
    for path in sorted(SRC_DIR.glob("*.pdf")):
        text = _first_page_text(path)
        pages.append((path, text))
        m_com = re.search(r"Comune/area:[^\S\n]*(\S[^\n]*)", text)
        m_code = re.search(r"Codice acquedotto:\s*(NG2[A-Z]{3})", text)
        if m_com and m_code:
            prefix_to_comune.setdefault(m_code.group(1), _clean(m_com.group(1).split(";")[0]))

    for path, text in pages:
        m = re.search(r"Comune/area:[^\S\n]*(\S[^\n]*)", text)
        if m:
            # Alcuni acquedotti servono due comuni ("Borgo Val di Taro;
            # Valmozzola"): il poligono usato è quello del primo.
            comune = _clean(m.group(1).split(";")[0])
        else:
            m_code = re.search(r"Codice acquedotto:\s*(NG2[A-Z]{3})", text)
            comune = prefix_to_comune.get(m_code.group(1), "") if m_code else ""
            if not comune:
                skipped.append((path.name, "comune/area non trovato"))
                continue
        m = re.search(r"Codice acquedotto:\s*(\S+)", text)
        code = _clean(m.group(1)) if m else path.stem[-10:]
        title = _clean(text.splitlines()[0]) if text else ""
        # Data campione nel titolo, in formati liberi: "campione del 18/11/2025",
        # "(campione del 16_09_2025)", "Campione del 10/7/25", "campione 05/08/2025".
        m = re.search(r"campione(?:\s+del)?\s+(\d{1,2})[/_](\d{1,2})[/_](\d{2,4})", title, re.I)
        zona = re.sub(r"\(?campione.*$", "", title, flags=re.I)
        zona = _clean(zona).strip(". (") or code
        if m:
            yy = int(m.group(3))
            d = date(yy + 2000 if yy < 100 else yy, int(m.group(2)), int(m.group(1)))
            periodo = f"{d.day:02d}/{d.month:02d}/{d.year:04d}"
        else:
            # Fallback: anno più recente nella colonna "Anno" della tabella.
            years = [int(y) for y in re.findall(r"\b(20\d{2})\s*$", text, re.M)]
            if not years:
                skipped.append((path.name, "data campione non trovata"))
                continue
            d = date(max(years), 1, 1)
            periodo = str(max(years))
        item = {
            "path": path,
            "comune": comune,
            "zona": zona,
            "code": code,
            "date": d,
            "periodo": periodo,
        }
        if code not in grouped or d > grouped[code]["date"]:
            grouped[code] = item
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

    entries, skipped = discover(polygons)
    print(f"[montagna2000] acquedotti selezionati: {len(entries)} / "
          f"{len(list(SRC_DIR.glob('*.pdf')))}")

    features = []
    for e in entries:
        key = _normalize(e["comune"])
        key = ALIASES.get(key, key)
        poly = polygons.get(key)
        if not poly:
            skipped.append((e["path"].name, f"polygon:{e['comune']}"))
            continue
        name = short_feature_name(
            PROVIDER_ID,
            f"{e['comune']}_{e['zona']}",
            f"{PROVIDER_ID}|{e['code']}",
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
    }, ensure_ascii=False), encoding="utf-8")
    print(f"[write] {OUT_FILE.name}: {len(features)} features")
    if skipped:
        print(f"[!] skipped {len(skipped)}:")
        for name, reason in skipped[:60]:
            print(f"   - {name}: {reason}")
    return 0 if features else 1


if __name__ == "__main__":
    sys.exit(main())
