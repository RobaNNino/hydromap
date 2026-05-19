"""
Build APS GeoJSON.

Scansiona i PDF "IMP*.pdf" (laboratorio Gruppo Maurizi per Acqua Pubblica
Sabina S.p.A.) presenti in backend/data/pdfs/, estrae da ciascuno il
comune servito (provincia di Rieti, prefisso ISTAT 057), raggruppa i PDF
per comune e per ognuno sceglie come "rappresentativo" il rapporto con la
data di emissione più recente.

Output: backend/data/mappa-qualita-aps.json con 1 feature per comune
(poligono ISTAT). La proprietà `name` della feature corrisponde allo stem
del PDF rappresentativo (es. "IMP4042"), così che parse_pdfs.py possa
collegarla automaticamente al record corrispondente in results.json.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).parent / "data"
PDF_DIR = ROOT / "pdfs"
OUT_GEOJSON = ROOT / "mappa-qualita-aps.json"
ISTAT_FILE = ROOT / "istat_comuni_italia.geojson"

# Estrae "Punto di prelievo: <Comune> (RI) - <descr>" con eventuale
# "Codice[ Comune]: NNNNNN" finale. Il codice è opzionale (i PDF di inizio
# 2024 non lo riportano).
RE_PUNTO = re.compile(
    # Provincia: RI (Rieti) o RM (sabina romana servita da APS).
    # "Codice" può essere seguito da ":" o solo spazio ("Codice 058061").
    r"Punto di prelievo:\s*([^()\-\n]+?)\s*\(\s*R[IM]\s*\)\s*(?:-\s*(.*?))?\s*(?:-\s*Codice(?:\s+Comune)?:?\s*(\d{6}))?\s*\(\$\)",
    re.IGNORECASE,
)
RE_EMIS = re.compile(r"Emissione rapporto:\s*(\d{2})/(\d{2})/(\d{4})")


def _parse_first_page_text(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return ""
        return pdf.pages[0].extract_text() or ""


def _normalize_comune(raw: str) -> str:
    s = re.sub(r"\s+", " ", raw).strip()
    # Title case ma rispetta apostrofi e preposizioni minuscole comuni.
    parts = s.lower().split(" ")
    out = []
    for w in parts:
        if w in {"di", "del", "della", "dello", "dei", "delle", "degli", "da", "in"}:
            out.append(w)
        else:
            out.append(w.capitalize() if w else w)
    if out:
        out[0] = out[0].capitalize()
    return " ".join(out)


def _scan_pdfs() -> list[dict]:
    """Estrae metadati da tutti gli IMP*.pdf."""
    pdfs = sorted(PDF_DIR.glob("IMP*.pdf"))
    print(f"[aps] scanning {len(pdfs)} IMP*.pdf …")
    records: list[dict] = []
    for i, p in enumerate(pdfs, 1):
        try:
            txt = _parse_first_page_text(p)
        except Exception as e:
            print(f"  ! {p.name}: {e!r}")
            continue
        m = RE_PUNTO.search(txt)
        if not m:
            continue
        comune = _normalize_comune(m.group(1))
        descr = (m.group(2) or "").strip()
        istat = m.group(3)
        me = RE_EMIS.search(txt)
        emis_iso = f"{me.group(3)}-{me.group(2)}-{me.group(1)}" if me else None
        records.append({
            "pdf": p.stem,
            "comune": comune,
            "descr": descr,
            "istat": istat,
            "emissione": emis_iso,
        })
        if i % 50 == 0:
            print(f"  scanned {i}/{len(pdfs)}")
    print(f"[aps] extracted {len(records)} records")
    return records


def _load_rieti_polygons() -> dict[str, dict]:
    """Carica i comuni della provincia di Rieti (codice 057*) dall'ISTAT."""
    print(f"[aps] loading ISTAT comuni …")
    data = json.loads(ISTAT_FILE.read_text(encoding="utf-8"))
    by_istat: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        # Schema openpolis: com_istat_code, name, prov_acr, prov_name
        code = str(props.get("com_istat_code") or "").zfill(6)
        # APS serve provincia di Rieti (057) + sabina romana (058) per
        # alcuni comuni (Monteflavio, Montorio Romano, Moricone, Nerola,
        # Palombara Sabina, Vallinfreda, ecc.).
        if not (code.startswith("057") or code.startswith("058")):
            continue
        name = props.get("name") or ""
        by_istat[code] = feat
        by_name[name.lower()] = feat
    print(f"[aps] loaded {len(by_istat)} comuni (Rieti + sabina romana)")
    return {"by_istat": by_istat, "by_name": by_name}


# Override per nomi comuni con varianti d'apostrofo o accentate.
NAME_OVERRIDES = {
    "Castel Sant'Angelo": "castel sant'angelo",
    "Cittareale": "cittareale",
    "Magliano Sabina": "magliano sabina",
    "Monte San Giovanni In Sabina": "monte san giovanni in sabina",
    "Santa Rufina": None,  # frazione di Cittaducale
}


def _match_polygon(rec: dict, idx: dict) -> dict | None:
    if rec["istat"]:
        feat = idx["by_istat"].get(rec["istat"])
        if feat is not None:
            return feat
    key = rec["comune"].lower()
    # Prova varianti
    for k in (key, key.replace("'", "'"), key.replace("'", "'")):
        feat = idx["by_name"].get(k)
        if feat is not None:
            return feat
    return None


def main() -> int:
    records = _scan_pdfs()
    if not records:
        print("[aps] no records extracted", file=sys.stderr)
        return 1
    idx = _load_rieti_polygons()

    # Raggruppa per comune (chiave = ISTAT se disponibile, altrimenti nome normalizzato).
    groups: dict[str, list[dict]] = defaultdict(list)
    unmatched: list[dict] = []
    for r in records:
        feat = _match_polygon(r, idx)
        if feat is None:
            unmatched.append(r)
            continue
        code = str((feat.get("properties") or {}).get("com_istat_code") or "").zfill(6)
        r["istat"] = code
        r["comune"] = (feat.get("properties") or {}).get("name") or r["comune"]
        groups[code].append(r)

    if unmatched:
        print(f"[aps] {len(unmatched)} unmatched records:")
        # mostra primi 10 nomi distinti
        seen = set()
        for r in unmatched:
            if r["comune"] not in seen:
                seen.add(r["comune"])
                print(f"  - {r['pdf']}: '{r['comune']}' istat={r['istat']}")
            if len(seen) >= 12:
                break

    features = []
    for code, items in groups.items():
        # PDF più recente per data di emissione
        items.sort(key=lambda x: x.get("emissione") or "", reverse=True)
        rep = items[0]
        feat = idx["by_istat"][code]
        props = dict(feat.get("properties") or {})
        features.append({
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": {
                "name": rep["pdf"],
                "comune": rep["comune"],
                "punto_prelievo": rep["descr"],
                "com_istat_code": code,
                "prov_acr": props.get("prov_acr") or "RI",
                "prov_name": props.get("prov_name") or "Rieti",
                "num_rapporti": len(items),
            },
        })

    out = {"type": "FeatureCollection", "features": features}
    OUT_GEOJSON.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"[aps] wrote {OUT_GEOJSON} ({len(features)} features, {len(groups)} comuni, "
          f"{sum(len(v) for v in groups.values())} PDFs grouped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
