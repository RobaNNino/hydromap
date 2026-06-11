"""
Build Romagna Acque runtime data (Società delle Fonti — rete all'ingrosso
della Romagna: province di Forlì-Cesena, Rimini e Ravenna).

Creates:
  - backend/data/mappa-qualita-romagnacque.json
  - backend/data/pdfs/romagnacque_<slug>.pdf

Sources:
  - backend/romagnacque_pdf/native_<code>_*.pdf      (media ultimo semestre)
  - backend/romagnacque_pdf/romagnacque_<code>.pdf   (analisi campione weblab)

I punti di prelievo sono nodi della rete all'ingrosso ("Consegna X",
"Uscita serbatoio Y"): vengono mappati sul poligono del comune riconosciuto
nella descrizione del punto (match diretto + alias per le frazioni note).
I punti non riconducibili a un comune (serbatoi montani minori, consegne a
San Marino) restano fuori mappa e vengono riportati a fine build.
Dedupe per punto: vince il campione con codice più recente; a parità,
il formato weblab (tabella completa con limiti).
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

SRC_DIR = HERE / "romagnacque_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-romagnacque.json"

PROVIDER_ID = "romagnacque"
PROVIDER_LABEL = "Romagna Acque"
PROVIDER_ATO = "Romagna (FC/RN/RA) - Società delle Fonti"

MAX_FEATURE_NAME_LEN = 80
PROVINCE = ("Forlì-Cesena", "Rimini", "Ravenna")

# Frazioni/abbreviazioni note -> comune ISTAT (chiavi e valori normalizzati).
ALIASES = {
    "santarcangelo": "santarcangelo di romagna",
    "bellaria": "bellaria igea marina",
    "bordonchio": "bellaria igea marina",
    "sogliano": "sogliano al rubicone",
    "castrocaro": "castrocaro terme e terra del sole",
    "morciano": "morciano di romagna",
    "montefiore": "montefiore conca",
    "torriana": "poggio torriana",
    "poggio berni": "poggio torriana",
    "misano": "misano adriatico",
    "cusercoli": "civitella di romagna",
    "calisese": "cesena",
    "pinarella": "cervia",
    "torre pedrera": "rimini",
    "covignano": "rimini",
    "villamarina": "cesenatico",
    "m saraceno": "mercato saraceno",
    "ridracoli": "bagno di romagna",
    "acquapartita": "bagno di romagna",
    "balze": "verghereto",
    "fratta terme": "bertinoro",
    "vecchiazzano": "forli",
    # Frazioni dell'alto Savio / Appennino forlivese
    "camposonaldo": "santa sofia",
    "cabelli": "santa sofia",
    "berleta": "santa sofia",
    "biserno": "santa sofia",
    "tavolicci": "verghereto",
    "castel alfero": "verghereto",
    "alfero": "verghereto",
    "montegranelli": "bagno di romagna",
    "monteguidi": "bagno di romagna",
    "valbonella": "bagno di romagna",
    "portico": "portico e san benedetto",
    "montepetra": "sogliano al rubicone",
    # Frazioni di pianura
    "s martino in strada": "forli",
    "villalta": "cesenatico",
    "budrio": "longiano",
    "dario campana": "rimini",
    "s giustina": "rimini",
    "s mauro in valle": "cesena",
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
        if props.get("prov_name") not in PROVINCE or not feat.get("geometry"):
            continue
        name = props.get("name") or ""
        out[_normalize(name)] = {
            "name": name,
            "provincia": props.get("prov_name") or "",
            "regione": props.get("reg_name") or "Emilia-Romagna",
            "geometry": feat["geometry"],
        }
    return out


def infer_comune_key(point_desc: str, polygons: dict[str, dict]) -> str:
    norm = _normalize(point_desc)
    best = ""
    for key in polygons:
        if re.search(rf"\b{re.escape(key)}\b", norm) and len(key) > len(best):
            best = key
    if best:
        return best
    for alias, target in sorted(ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", norm) and target in polygons:
            return target
    return ""


def _first_page_text(path: Path) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            return pdf.pages[0].extract_text() or ""
    except Exception:
        return ""


def discover(polygons: dict[str, dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    grouped: dict[str, dict] = {}
    skipped: list[tuple[str, str]] = []
    for path in sorted(SRC_DIR.glob("*.pdf")):
        text = _first_page_text(path)
        m = re.search(r"Punto (?:di )?prelievo:\s*([^\n|]+)", text)
        if not m:
            skipped.append((path.name, "punto di prelievo non trovato"))
            continue
        point = _clean(m.group(1))
        # Id punto: token prima del separatore ("21.1 - Consegna..." / "CRM_15_Alfonsine")
        m_id = re.match(r"(?:CRM[_\s]*)?([0-9]+[0-9a-zA-Z./]*)\s*[-_]", point)
        point_id = m_id.group(1).lower() if m_id else slugify(point)[:20]
        desc = re.sub(r"^(?:CRM[_\s]*)?[0-9]+[0-9a-zA-Z./]*\s*[-_]\s*", "", point) or point
        m_code = re.search(r"(2\dLA\d+)", path.stem)
        sample_code = m_code.group(1) if m_code else "00LA0"
        is_weblab = path.stem.startswith("romagnacque_")
        rank = (sample_code, 1 if is_weblab else 0, len(desc))
        cur = grouped.get(point_id)
        if cur is None or rank > cur["rank"]:
            grouped[point_id] = {
                "path": path,
                "point_id": point_id,
                "desc": desc,
                "rank": rank,
                "sample_code": sample_code,
                "year": 2000 + int(sample_code[:2]),
            }

    entries = []
    for e in sorted(grouped.values(), key=lambda x: x["point_id"]):
        key = infer_comune_key(e["desc"], polygons)
        if not key:
            skipped.append((e["path"].name, f"comune non riconosciuto: {e['desc']}"))
            continue
        e["comune_key"] = key
        entries.append(e)
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

    entries, skipped = discover(polygons)
    print(f"[romagnacque] punti mappati: {len(entries)} "
          f"(da {len(list(SRC_DIR.glob('*.pdf')))} PDF)")

    features = []
    for e in entries:
        poly = polygons[e["comune_key"]]
        name = short_feature_name(
            PROVIDER_ID,
            f"{poly['name']}_{e['desc']}",
            f"{PROVIDER_ID}|{e['point_id']}",
        )
        shutil.copy2(e["path"], PDF_OUT_DIR / f"{name}.pdf")
        lat, lon = _center(poly["geometry"])
        features.append({
            "type": "Feature",
            "geometry": poly["geometry"],
            "properties": {
                "name": name,
                "comune": poly["name"],
                "zona_label": e["desc"],
                "regione": poly["regione"],
                "provincia": poly["provincia"],
                "provider": PROVIDER_ID,
                "provider_label": PROVIDER_LABEL,
                "provider_ato": PROVIDER_ATO,
                "periodo": str(e["year"]),
                "lat": lat,
                "lon": lon,
                "source_pdf": e["path"].name,
                "source_year": e["year"],
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
