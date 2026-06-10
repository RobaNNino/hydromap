"""
Build Marche runtime data.

Creates:
  - backend/data/mappa-qualita-marche-batch.json
  - backend/data/mappa-qualita-marche-multiservizi.json
  - backend/data/pdfs/marche_<provider>_<slug>.pdf

Sources:
  - backend/marche_batch_pdf/<provider>/*.pdf
  - backend/marche_multiservizi_pdf/*.pdf

Only recent source documents are included. For folders with historical series,
the latest document per sampling zone is selected; 2023 is accepted only when no
newer report exists for that same zone.
"""
from __future__ import annotations

import json
import hashlib
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
ISTAT_GEOJSON = DATA_DIR / "istat_comuni_italia.geojson"

SRC_BATCH = HERE / "marche_batch_pdf"
SRC_MULTISERVIZI = HERE / "marche_multiservizi_pdf"

OUT_BATCH = DATA_DIR / "mappa-qualita-marche-batch.json"
OUT_MULTISERVIZI = DATA_DIR / "mappa-qualita-marche-multiservizi.json"

MIN_YEAR = 2023
MAX_FEATURE_NAME_LEN = 80

PROVIDERS = {
    "marche_apmgroup": {
        "label": "APM Group",
        "ato": "ATO 3 Marche Centro - Macerata",
        "url": "https://www.apmgroup.it/",
    },
    "marche_assemspa": {
        "label": "A.S.SE.M. S.p.A.",
        "ato": "ATO 3 Marche Centro - Macerata",
        "url": "https://www.assemspa.it/",
    },
    "marche_asteaspa": {
        "label": "ASTEA S.p.A.",
        "ato": "ATO 3 Marche Centro - Macerata",
        "url": "https://www.asteaspa.it/",
    },
    "marche_atac_civitanova": {
        "label": "ATAC Civitanova S.p.A.",
        "ato": "ATO 3 Marche Centro - Macerata",
        "url": "https://www.atac-civitanova.it/",
    },
    "marche_vivaservizi": {
        "label": "Viva Servizi S.p.A.",
        "ato": "ATO 2 Marche Centro - Ancona",
        "url": "https://www.vivaservizi.it/",
    },
    "marche_multiservizi": {
        "label": "Marche Multiservizi S.p.A.",
        "ato": "ATO 1 Marche Nord - Pesaro e Urbino",
        "url": "https://www.gruppomarchemultiservizi.it/",
    },
}

PROVIDER_PREFIX = {
    "apmgroup": "marche_apmgroup",
    "assemspa": "marche_assemspa",
    "asteaspa": "marche_asteaspa",
    "atac_civitanova": "marche_atac_civitanova",
    "vivaservizi": "marche_vivaservizi",
}

MONTHS_IT = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}

ALIASES = {
    "civitanova": "civitanova marche",
    "falconara": "falconara marittima",
    "fratterosa": "fratte rosa",
    "castelcolonna": "trecastelli",
    "monterado": "trecastelli",
    "ripe": "trecastelli",
    "montemaggiore": "colli al metauro",
    "saltara": "colli al metauro",
    "serrungarina": "colli al metauro",
    "barchi": "terre roveresche",
    "orciano": "terre roveresche",
    "piagge": "terre roveresche",
    "san giorgio": "terre roveresche",
    "sassocorvaro": "sassocorvaro auditore",
    "auditore": "sassocorvaro auditore",
    "monteciccardo": "pesaro",
    "serra dei conti": "serra de conti",
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


def _label_from_stem(stem: str) -> str:
    return stem.replace("_", " ").replace(" - ", " - ").strip()


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s.lower())).strip()


def _parts_from_stem(stem: str) -> list[str]:
    return [_clean(p.replace("_", " ")) for p in stem.split("_-_") if _clean(p)]


def _parse_date_token(token: str) -> date | None:
    token = token.strip()
    m = re.search(r"\b(\d{1,2})[\/_.-](\d{1,2})[\/_.-](20\d{2}|\d{2})\b", token)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3))
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[\/_.-](20\d{2})\b", token)
    if m:
        month = int(m.group(1))
        year = int(m.group(2))
        try:
            return date(year, month, 1)
        except ValueError:
            return None
    m = re.search(r"\b(" + "|".join(MONTHS_IT) + r")\s+(20\d{2})\b", token, re.I)
    if m:
        return date(int(m.group(2)), MONTHS_IT[m.group(1).lower()], 1)
    m = re.search(r"\b(20\d{2})\b", token)
    if m:
        return date(int(m.group(1)), 6, 1)
    return None


def _periodo(d: date | None) -> str:
    if not d:
        return ""
    if d.day == 1:
        return f"{d.month:02d}/{d.year:04d}"
    return f"{d.day:02d}/{d.month:02d}/{d.year:04d}"


def _extract_text(path: Path, pages: int = 1) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            chunks = []
            for page in pdf.pages[:pages]:
                chunks.append(page.extract_text() or "")
            return "\n".join(chunks)
    except Exception:
        return ""


def _date_from_pdf(path: Path) -> date | None:
    text = _extract_text(path, pages=1)
    patterns = [
        r"Data prelievo:\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"Valori rilevati il\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"Valori rilevati dal\s*\d{1,2}/\d{1,2}/\d{2,4}\s+al\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"Data campionamento:\s*[¹\s]*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"Riferimento Rapporto di Prova[^\\n]*?\sdel\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"\bANNO\s+(20\d{2})\b",
    ]
    found: list[date] = []
    for pat in patterns:
        for value in re.findall(pat, text, re.I):
            d = _parse_date_token(value)
            if d:
                found.append(d)
    d = max(found) if found else None
    if d:
        return d

    # Fallback dal nome file: usato per PDF scansionati che portano il mese/anno
    # nel titolo (es. Astea "04-2026").
    stem = path.stem.replace("_", " ")
    matches = []
    for m in re.finditer(r"\b(\d{1,2})[\/_.-](20\d{2})\b", path.stem):
        candidate = _parse_date_token(m.group(0))
        if candidate:
            matches.append(candidate)
    for m in re.finditer(r"\b(" + "|".join(MONTHS_IT) + r")\s+(20\d{2})\b", stem, re.I):
        matches.append(date(int(m.group(2)), MONTHS_IT[m.group(1).lower()], 1))
    for m in re.finditer(r"\b(20\d{2})\b", path.stem):
        matches.append(date(int(m.group(1)), 6, 1))
    return max(matches) if matches else None


def load_marche_polygons() -> dict[str, dict]:
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        if props.get("reg_name") != "Marche" or not feat.get("geometry"):
            continue
        name = props.get("name") or ""
        key = _normalize(name)
        out[key] = {
            "name": name,
            "provincia": props.get("prov_name") or "",
            "regione": props.get("reg_name") or "Marche",
            "geometry": feat["geometry"],
        }
    return out


def infer_comune(label: str, polygons: dict[str, dict]) -> str:
    norm = _normalize(label)
    compact_norm = norm.replace(" ", "")
    direct = ALIASES.get(norm)
    if direct:
        return polygons.get(direct, {}).get("name", label)

    best_key = ""
    for key in polygons:
        compact_key = key.replace(" ", "")
        if key and (re.search(rf"\b{re.escape(key)}\b", norm)
                    or (compact_key and compact_key in compact_norm)):
            if len(key) > len(best_key):
                best_key = key
    if best_key:
        return polygons[best_key]["name"]

    # Second pass su alias contenuti in etichette composite/frazioni.
    for alias, target in sorted(ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", norm) and target in polygons:
            return polygons[target]["name"]
    return label.strip()


def _zone_after_comune(label: str, comune: str) -> str:
    label_clean = _clean(label.replace("_", " "))
    comune_norm = _normalize(comune)
    tokens = label_clean.split()
    for i in range(len(tokens)):
        left = _normalize(" ".join(tokens[:i + 1]))
        if left == comune_norm:
            return _clean(" ".join(tokens[i + 1:]).strip(" -()"))
    return ""


def _entry(provider: str, path: Path, comune: str, zona: str, d: date | None) -> dict | None:
    if not d or d.year < MIN_YEAR:
        return None
    return {
        "provider": provider,
        "path": path,
        "comune": comune,
        "zona": zona,
        "date": d,
        "periodo": _periodo(d),
    }


def discover_apmgroup(root: Path) -> list[dict]:
    out = []
    for path in sorted(root.glob("*.pdf")):
        parts = _parts_from_stem(path.stem)
        comune = parts[0] if parts else ""
        zona = parts[1] if len(parts) > 1 else comune
        d = _date_from_pdf(path)
        item = _entry("marche_apmgroup", path, comune, zona, d)
        if item:
            out.append(item)
    return out


def discover_assemspa(root: Path, polygons: dict[str, dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for path in sorted(root.glob("*.pdf")):
        d = _date_from_pdf(path)
        if not d or d.year < MIN_YEAR:
            continue
        parts = _parts_from_stem(path.stem)
        comune = ""
        zona = ""
        if len(parts) >= 3:
            # Analisi_<Comune>_<anno>_-_<zona>_(sample_date)
            head = parts[0]
            m = re.match(r"Analisi\s+(.+?)\s+20\d{2}$", head, re.I)
            comune = m.group(1) if m else head.replace("Analisi ", "")
            zona = re.sub(r"\s*\(.*$", "", parts[1])
        else:
            label = _label_from_stem(path.stem)
            comune = infer_comune(label, polygons)
            zona = _zone_after_comune(label, comune) or label
        key = slugify(f"{comune}_{zona}")
        item = _entry("marche_assemspa", path, comune, zona, d)
        if item and (key not in grouped or item["date"] > grouped[key]["date"]):
            grouped[key] = item
    return sorted(grouped.values(), key=lambda x: (x["comune"], x["zona"]))


def discover_asteaspa(root: Path, polygons: dict[str, dict]) -> list[dict]:
    out = []
    for path in sorted(root.glob("*.pdf")):
        d = _date_from_pdf(path)
        if not d or d.year < MIN_YEAR:
            continue
        label = _label_from_stem(path.stem)
        comune = infer_comune(label, polygons)
        zona = _zone_after_comune(label, comune) or label
        item = _entry("marche_asteaspa", path, comune, zona, d)
        if item:
            out.append(item)
    return out


def discover_atac(root: Path) -> list[dict]:
    out = []
    for path in sorted(root.glob("*.pdf")):
        d = _date_from_pdf(path)
        if not d or d.year < MIN_YEAR:
            continue
        text = _extract_text(path, pages=1)
        if "Parametri" not in text or "Risultati" not in text:
            continue
        m = re.search(r"INDIRIZZO DI FORNITURA:\s*[“\"]([^”\"]+)", text, re.I)
        zona = _clean(m.group(1)) if m else _label_from_stem(path.stem)
        item = _entry("marche_atac_civitanova", path, "Civitanova Marche", zona, d)
        if item:
            out.append(item)
    return out


def discover_vivaservizi(root: Path, polygons: dict[str, dict]) -> list[dict]:
    out = []
    for path in sorted(root.glob("*.pdf")):
        d = _date_from_pdf(path)
        if not d or d.year < MIN_YEAR:
            continue
        parts = _parts_from_stem(path.stem)
        label = parts[1] if len(parts) > 1 else _label_from_stem(path.stem)
        label = re.sub(r"\s+\d+$", "", label)
        comune = infer_comune(label, polygons)
        zona = _zone_after_comune(label, comune)
        item = _entry("marche_vivaservizi", path, comune, zona or comune, d)
        if not item:
            continue
        if path.name.startswith("Nuovi_parametri"):
            item["zona"] = f"{item['zona']} - nuovi parametri"
        out.append(item)
    return sorted(out, key=lambda x: (x["comune"], x["zona"], x["path"].name))


def discover_multiservizi(root: Path, polygons: dict[str, dict]) -> list[dict]:
    out = []
    for path in sorted(root.glob("*.pdf")):
        d = _date_from_pdf(path)
        if not d or d.year < MIN_YEAR:
            continue
        parts = _parts_from_stem(path.stem)
        if len(parts) >= 3 and parts[0].lower().startswith("qualita"):
            comune = infer_comune(parts[1], polygons)
            zona = parts[2]
        else:
            label = _label_from_stem(path.stem)
            label = re.sub(r"^Qualita dell'?acqua\s*(?:di\s*)?", "", label, flags=re.I).strip(" -")
            comune = infer_comune(label, polygons)
            zona = _zone_after_comune(label, comune) or comune
        item = _entry("marche_multiservizi", path, comune, zona, d)
        if item:
            out.append(item)
    return out


def _iter_points(coords):
    if not coords:
        return
    first = coords[0]
    if isinstance(first, (int, float)):
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


def write_geojson(entries: list[dict], polygons: dict[str, dict], out_file: Path) -> tuple[int, list[tuple[str, str]]]:
    features = []
    skipped = []
    for e in entries:
        comune_key = _normalize(e["comune"])
        comune_key = ALIASES.get(comune_key, comune_key)
        poly = polygons.get(comune_key)
        if not poly:
            skipped.append((e["path"].name, f"polygon:{e['comune']}"))
            continue
        name = short_feature_name(
            e["provider"],
            f"{e['comune']}_{e['zona']}",
            f"{e['provider']}|{e['path'].as_posix()}|{e['date'].isoformat()}",
        )
        dest = PDF_OUT_DIR / f"{name}.pdf"
        shutil.copy2(e["path"], dest)
        lat, lon = _center(poly["geometry"])
        meta = PROVIDERS[e["provider"]]
        features.append({
            "type": "Feature",
            "geometry": poly["geometry"],
            "properties": {
                "name": name,
                "comune": poly["name"],
                "zona_label": e["zona"],
                "regione": poly["regione"],
                "provincia": poly["provincia"],
                "provider": e["provider"],
                "provider_label": meta["label"],
                "provider_ato": meta["ato"],
                "periodo": e["periodo"],
                "lat": lat,
                "lon": lon,
                "source_pdf": e["path"].name,
                "source_year": e["date"].year,
            },
        })
    out_file.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
        "_built_at": datetime.now(timezone.utc).isoformat(),
        "_min_year": MIN_YEAR,
    }, ensure_ascii=False), encoding="utf-8")
    return len(features), skipped


def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)
    polygons = load_marche_polygons()
    for old in PDF_OUT_DIR.glob("marche_*.pdf"):
        old.unlink()

    batch_entries: list[dict] = []
    skipped_sources: list[tuple[str, str]] = []

    if SRC_BATCH.exists():
        for folder in sorted(p for p in SRC_BATCH.iterdir() if p.is_dir()):
            key = folder.name
            if key == "apmgroup":
                entries = discover_apmgroup(folder)
            elif key == "assemspa":
                entries = discover_assemspa(folder, polygons)
            elif key == "asteaspa":
                entries = discover_asteaspa(folder, polygons)
            elif key == "atac_civitanova":
                entries = discover_atac(folder)
            elif key == "vivaservizi":
                entries = discover_vivaservizi(folder, polygons)
            else:
                entries = []
            batch_entries.extend(entries)
            total = len(list(folder.glob("*.pdf")))
            print(f"[batch] {key}: selected {len(entries)} / {total}")
    else:
        print(f"[!] sorgente non trovata: {SRC_BATCH}")

    multi_entries = discover_multiservizi(SRC_MULTISERVIZI, polygons) if SRC_MULTISERVIZI.exists() else []
    print(f"[multiservizi] selected {len(multi_entries)} / {len(list(SRC_MULTISERVIZI.glob('*.pdf'))) if SRC_MULTISERVIZI.exists() else 0}")

    n_batch, skipped = write_geojson(batch_entries, polygons, OUT_BATCH)
    skipped_sources.extend(skipped)
    n_multi, skipped = write_geojson(multi_entries, polygons, OUT_MULTISERVIZI)
    skipped_sources.extend(skipped)

    print(f"[write] {OUT_BATCH.name}: {n_batch} features")
    print(f"[write] {OUT_MULTISERVIZI.name}: {n_multi} features")
    if skipped_sources:
        print(f"[!] skipped {len(skipped_sources)} entries:")
        for name, reason in skipped_sources[:80]:
            print(f"   - {name}: {reason}")
    return 0 if (n_batch or n_multi) else 1


if __name__ == "__main__":
    sys.exit(main())
