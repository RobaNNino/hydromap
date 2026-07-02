"""
Build Gruppo Hera runtime data (zone di fornitura idropotabile "che acqua bevi").

Creates:
  - backend/data/mappa-qualita-gruppohera.json
  - backend/data/pdfs/gruppohera_<slug>.pdf

Sources:
  - backend/gruppohera_zdf_best_pdf/*.pdf   (una scheda per zona di fornitura)

Tra le varianti di scraping disponibili (zdf / zdf_best / zdf_deep) viene usata
zdf_best: zdf e zdf_best sono identiche (150 zone), zdf_deep è un sottoinsieme
(133); la cartella gruppohera_pdf contiene solo medie provinciali senza
granularità di zona.

Ogni scheda riporta il "Civic key" dell'indirizzo campione, che inizia con il
codice ISTAT del comune (es. 036026 = Montese): il poligono comunale viene
risolto da quello, con fallback sul nome del comune nell'indirizzo.

Una zona di fornitura può servire più comuni (es. PONTELAGOSCURO copre
Ferrara, Argenta, Voghiera, ...): il nome feature è quindi per coppia
(zona, comune). I file con il marcatore "__<COMUNE>" prodotti da
build_gruppohera_zdf_pdfs.py hanno priorità sui vecchi file per-zona quando
risolvono la stessa coppia (zona, comune).
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

SRC_DIR = HERE / "gruppohera_zdf_best_pdf"
OUT_FILE = DATA_DIR / "mappa-qualita-gruppohera.json"

PROVIDER_ID = "gruppohera"
PROVIDER_LABEL = "Gruppo Hera"
PROVIDER_ATO = "ATERSIR Emilia-Romagna e territori Gruppo Hera"

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


def _pretty_zone(s: str) -> str:
    return _clean(s.replace("_", " ")).title()


def load_polygons() -> tuple[dict[str, dict], dict[str, dict]]:
    """Poligoni comunali indicizzati per codice ISTAT e per nome normalizzato."""
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    by_code: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        if not feat.get("geometry"):
            continue
        code = str(props.get("com_istat_code") or "")
        entry = {
            "name": props.get("name") or "",
            "provincia": props.get("prov_name") or "",
            "regione": props.get("reg_name") or "",
            "geometry": feat["geometry"],
            "code": code,
        }
        if code:
            by_code[code] = entry
        by_name[_normalize(entry["name"])] = entry
    return by_code, by_name


def _zone_extra_polys(zona: str, er_by_name: dict[str, dict],
                      primary_code: str) -> list[dict]:
    """Comuni AGGIUNTIVI citati nel nome della zona di fornitura (es.
    'Modena Big' -> Modena; 'Sassuolo Fiorano Maranello' -> tutti e tre;
    'Vignola Savignano Sul Panaro' -> Vignola + Savignano sul Panaro).

    Conservativo: finestre di parole (dalla piu' lunga), match esatto sul nome
    normalizzato oppure prefisso-a-parole UNICO, limitato alle PROVINCE in cui
    Hera gestisce l'acquedotto (evita che frazioni omonime come 'San Pellegrino'
    o 'Montecchio' catturino comuni di RE/PR/Marche); i token singoli corti
    (<5 char) sono ignorati."""
    toks = _normalize(zona).split()
    out: list[dict] = []
    used = [False] * len(toks)
    keys = list(er_by_name.keys())
    for win in (4, 3, 2, 1):
        for i in range(len(toks) - win + 1):
            if any(used[i:i + win]):
                continue
            q = " ".join(toks[i:i + win])
            if win == 1 and len(q) < 5:
                continue
            hit = er_by_name.get(q)
            if not hit:
                pref = [k for k in keys if k.startswith(q + " ")]
                if len(pref) == 1:
                    hit = er_by_name[pref[0]]
            if hit and hit["code"] != primary_code and hit not in out:
                out.append(hit)
                for j in range(i, i + win):
                    used[j] = True
    return out


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
    by_code, by_name = load_polygons()
    for old in PDF_OUT_DIR.glob(f"{PROVIDER_ID}_*.pdf"):
        old.unlink()

    features = []
    skipped = []
    seen_names: set[str] = set()
    # sotto-indice per l'estrazione dei comuni extra dal nome zona:
    # SOLO le province servite da Hera/Heracqua per l'acquedotto
    _HERA_PROV = ("Modena", "Bologna", "Ferrara", "Ravenna",
                  "Forlì-Cesena", "Rimini")
    er_by_name = {k: v for k, v in by_name.items()
                  if v.get("provincia") in _HERA_PROV}
    # i file per-(zona, comune) con marcatore "__" prima dei vecchi per-zona,
    # così a parità di coppia vince la scansione più recente
    src_files = sorted(SRC_DIR.glob("*.pdf"),
                       key=lambda p: (0 if "__" in p.stem else 1, p.name))
    for path in src_files:
        text = _first_page_text(path)
        m_zona = re.search(r"fornitura idropotabile:</b>\s*([^\n<]+)", text)
        m_gest = re.search(r"Gestore:</b>\s*([^\n<]+)", text)
        m_addr = re.search(r"Indirizzo campione:</b>\s*([^\n<]+)", text)
        m_civ = re.search(r"Civic key:</b>\s*(\d{6})", text)
        if not m_zona:
            skipped.append((path.name, "zona di fornitura non trovata"))
            continue
        zona = _pretty_zone(m_zona.group(1))
        gestore = _clean(m_gest.group(1)) if m_gest else "HERA"
        poly = by_code.get(m_civ.group(1)) if m_civ else None
        if not poly and m_addr:
            comune_addr = _clean(m_addr.group(1)).split(",")[0]
            poly = by_name.get(_normalize(comune_addr))
        if not poly:
            skipped.append((path.name, f"polygon: civ={m_civ.group(1) if m_civ else '-'} addr={m_addr.group(1)[:40] if m_addr else '-'}"))
            continue
        # comune primario (civic key / indirizzo) + comuni citati nel nome zona
        polys = [poly] + _zone_extra_polys(zona, er_by_name, poly["code"])
        first = True
        for pl in polys:
            name = short_feature_name(
                PROVIDER_ID,
                f"{pl['name']}_{zona}",
                f"{PROVIDER_ID}|{gestore}|{zona}|{pl['code'] or pl['name']}",
            )
            if name in seen_names:
                if first:
                    skipped.append((path.name, f"duplicato (zona, comune): {zona} / {pl['name']}"))
                first = False
                continue
            first = False
            seen_names.add(name)
            shutil.copy2(path, PDF_OUT_DIR / f"{name}.pdf")
            lat, lon = _center(pl["geometry"])
            features.append({
                "type": "Feature",
                "geometry": pl["geometry"],
                "properties": {
                    "name": name,
                    "comune": pl["name"],
                    "zona_label": zona,
                    "regione": pl["regione"],
                    "provincia": pl["provincia"],
                    "provider": PROVIDER_ID,
                    "provider_label": PROVIDER_LABEL,
                    "provider_ato": PROVIDER_ATO,
                    "periodo": "",
                    "lat": lat,
                    "lon": lon,
                    "source_pdf": path.name,
                },
            })

    OUT_FILE.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
        "_built_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    print(f"[write] {OUT_FILE.name}: {len(features)} features "
          f"(da {len(list(SRC_DIR.glob('*.pdf')))} PDF)")
    if skipped:
        print(f"[!] skipped {len(skipped)}:")
        for name, reason in skipped[:40]:
            print(f"   - {name}: {reason}")
    return 0 if features else 1


if __name__ == "__main__":
    sys.exit(main())
