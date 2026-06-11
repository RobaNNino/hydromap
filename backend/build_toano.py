"""
Build AST Toano runtime data (Azienda Speciale Toano, comune di Toano - RE).

Creates:
  - backend/data/mappa-qualita-toano.json
  - backend/data/pdfs/toano_<slug>.pdf

Sources:
  - backend/acquatoano_pdf/<anno>_<Punto>_del_<dd-mm-yyyy>.pdf

Rapporti di prova di laboratorio (eMMe.2 srl) per i punti di campionamento
delle frazioni di Toano (serbatoi e pozzetti). Tutte le feature condividono
il poligono comunale di Toano (il frontend disambigua); per ciascun punto
viene tenuto il rapporto più recente, identificando il punto tramite il
codice interno "AST_TOANO_<sigla>" presente nel testo.
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

SRC_DIR = HERE / "acquatoano_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-toano.json"

PROVIDER_ID = "toano"
PROVIDER_LABEL = "AST - Azienda Speciale Toano"
PROVIDER_ATO = "Comune di Toano (RE)"

MAX_FEATURE_NAME_LEN = 80

# Lo stesso serbatoio compare con nomi file diversi nei due anni: uniforma il
# codice di dedupe quando il PDF non espone il codice AST nel testo.
FALLBACK_CODE_ALIASES = {
    "serbatoio_case_magnani_casella": "CASELLA_MAGNANI",
    "serbatoio_casella_casa_magnani": "CASELLA_MAGNANI",
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


def load_toano_polygon() -> dict | None:
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        if props.get("reg_name") == "Emilia-Romagna" \
                and _normalize(props.get("name") or "") == "toano" \
                and feat.get("geometry"):
            return {
                "name": props.get("name"),
                "provincia": props.get("prov_name") or "",
                "regione": "Emilia-Romagna",
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
    poly = load_toano_polygon()
    if not poly:
        print("[!] poligono di Toano non trovato nell'ISTAT geojson")
        return 1
    for old in PDF_OUT_DIR.glob(f"{PROVIDER_ID}_*.pdf"):
        old.unlink()

    grouped: dict[str, dict] = {}
    skipped = []
    for path in sorted(SRC_DIR.glob("*.pdf")):
        text = _first_page_text(path)
        # Codice punto: "(AST_TOANO_CVPC_16-SERBATOIO CAVOLA)" (eMMe.2) oppure
        # "Descrizione campione: AST_TOANO_CUPC_19- Località Corneto" (Iren Lab).
        m = re.search(r"AST_TOANO_([A-Z0-9_]+?)\s*-\s*([^)\n]+)", text)
        if m:
            code = m.group(1)
            zona = _clean(m.group(2)).title()
        else:
            # Fallback dal nome file: "<anno>_<Punto>_del_<data>"
            stem_label = re.sub(r"^\d{4}_", "", path.stem)
            stem_label = re.sub(r"_del_\d{2}-\d{2}-\d{4}$", "", stem_label)
            zona = _clean(stem_label.replace("_", " ")).title()
            code = FALLBACK_CODE_ALIASES.get(slugify(zona), slugify(zona))
        m = re.search(r"IN\s*\n?DATA:\s*(\d{1,2})/(\d{1,2})/(\d{4})", text) \
            or re.search(r"DATA:\s*(\d{1,2})/(\d{1,2})/(\d{4})", text) \
            or re.search(r"Campionato il:\s*(\d{1,2})/(\d{1,2})/(\d{4})", text) \
            or re.search(r"_del_(\d{2})-(\d{2})-(\d{4})", path.stem)
        if not m:
            skipped.append((path.name, "data campionamento non trovata"))
            continue
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        item = {
            "path": path,
            "zona": zona,
            "code": code,
            "date": d,
            "periodo": f"{d.day:02d}/{d.month:02d}/{d.year:04d}",
        }
        if code not in grouped or d > grouped[code]["date"]:
            grouped[code] = item

    features = []
    lat, lon = _center(poly["geometry"])
    for code, e in sorted(grouped.items()):
        name = short_feature_name(PROVIDER_ID, e["zona"], f"{PROVIDER_ID}|{code}")
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
    print(f"[write] {OUT_FILE.name}: {len(features)} features "
          f"(da {len(list(SRC_DIR.glob('*.pdf')))} PDF)")
    for name, reason in skipped:
        print(f"   ! {name}: {reason}")
    return 0 if features else 1


if __name__ == "__main__":
    sys.exit(main())
