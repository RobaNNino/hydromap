"""
Build IREN Acqua runtime data (Gruppo IREN — Emilia-Romagna, Liguria, Piemonte).

Creates:
  - backend/data/mappa-qualita-iren.json
  - backend/data/pdfs/iren_acqua_<slug>.pdf

Sources:
  - backend/iren_acqua_pdf/*.pdf   (una scheda per comune/zona dal portale Iren)

Comune, zona, regione e periodo vengono letti dal testo del PDF (righe fisse:
"<COMUNE> - <zona>" / "<Regione> / Provincia di <Prov> (<SIGLA>)" /
"Periodo dal YYYY-MM-DD al YYYY-MM-DD"). Ogni scheda diventa una feature col
poligono comunale ISTAT della regione corrispondente; più zone nello stesso
comune = più feature sovrapposte (il frontend ha il selettore).
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

SRC_DIR = HERE / "iren_acqua_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-iren.json"

PROVIDER_ID = "iren_acqua"
PROVIDER_LABEL = "IREN Acqua"
PROVIDER_ATO = "Gruppo IREN - Emilia-Romagna, Liguria, Piemonte"

MAX_FEATURE_NAME_LEN = 80

# Comuni soppressi/fusi o con grafie diverse rispetto a ISTAT.
ALIASES = {
    "busana": "ventasso",
    "collagna": "ventasso",
    "ligonchio": "ventasso",
    "ramiseto": "ventasso",
    "reggio emilia": "reggio nell emilia",
    "caminata": "alta val tidone",     # fusi nel 2018
    "nibbiano": "alta val tidone",
    "pecorara": "alta val tidone",
    "mezzani": "sorbolo mezzani",      # fusi nel 2019
    "sorbolo": "sorbolo mezzani",
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


def load_polygons() -> dict[tuple[str, str], dict]:
    """Poligoni comunali ISTAT indicizzati per (regione, comune) normalizzati."""
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], dict] = {}
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        if not feat.get("geometry"):
            continue
        name = props.get("name") or ""
        reg = props.get("reg_name") or ""
        out[(_normalize(reg), _normalize(name))] = {
            "name": name,
            "provincia": props.get("prov_name") or "",
            "regione": reg,
            "geometry": feat["geometry"],
        }
    return out


def _first_page_text(path: Path) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            return pdf.pages[0].extract_text() or ""
    except Exception:
        return ""


def discover() -> tuple[list[dict], list[tuple[str, str]]]:
    entries: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for path in sorted(SRC_DIR.glob("*.pdf")):
        text = _first_page_text(path)
        m_reg = re.search(
            r"^(.+?)\s*/\s*Provincia di\s+(.+?)\s*\(([A-Za-z]{2})\)\s*$", text, re.M)
        if not m_reg:
            skipped.append((path.name, "riga regione/provincia non trovata"))
            continue
        regione = _clean(m_reg.group(1))
        # La riga del titolo "<COMUNE> - <zona>" precede quella della regione;
        # per le etichette zona molto lunghe il titolo va a capo su due righe.
        lines = text.splitlines()
        idx = next((i for i, line in enumerate(lines)
                    if line.strip() == m_reg.group(0).strip()), -1)
        title = _clean(lines[idx - 1]) if idx >= 1 else ""
        m_title = re.match(r"^(.+?)\s+-\s+(.+)$", title)
        if not m_title and idx >= 2:
            title = _clean(f"{lines[idx - 2]} {lines[idx - 1]}")
            m_title = re.match(r"^(.+?)\s+-\s+(.+)$", title)
        if not m_title:
            skipped.append((path.name, f"titolo comune/zona non trovato: {title!r}"))
            continue
        comune = _clean(m_title.group(1)).title()
        zona = _clean(m_title.group(2))
        m_per = re.search(r"Periodo dal\s+\d{4}-\d{2}-\d{2}\s+al\s+(\d{4})-(\d{2})-\d{2}", text)
        periodo = f"{m_per.group(2)}/{m_per.group(1)}" if m_per else ""
        entries.append({
            "path": path,
            "regione": regione,
            "comune": comune,
            "zona": zona,
            "periodo": periodo,
        })
    return entries, skipped


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

    entries, skipped = discover()
    print(f"[iren] schede lette: {len(entries)} / {len(list(SRC_DIR.glob('*.pdf')))}")

    features = []
    for e in entries:
        key_com = _normalize(e["comune"])
        key_com = ALIASES.get(key_com, key_com)
        poly = polygons.get((_normalize(e["regione"]), key_com))
        if not poly:
            skipped.append((e["path"].name, f"polygon:{e['regione']}/{e['comune']}"))
            continue
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
