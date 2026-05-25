"""
build_abruzzo.py
================

Costruisce:
  - backend/data/mappa-qualita-abruzzo.json   (GeoJSON poligoni comunali)
  - backend/data/pdfs/abruzzo_<provider>_<slug>.pdf   (PDF rappresentativi)

Provider supportati (cartella sorgente: abruzzo_pdf/):
  - CAM_spa       → cam            (1 PDF per comune, schema piatto)
  - Ruzzo_Reti    → ruzzo          (multi-PDF datati per comune → latest)
  - ACA_Pescara   → aca            (multi-sito per comune → primo signed)
  - SASI_spa      → sasi           (mese più recente in "Dati Acqua 2026")

I poligoni vengono geocodificati via Nominatim (polygon_geojson=1) con
cache su disco (data/abruzzo_polygons_cache.json) per ridurre richieste.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SRC_DIR = HERE / "data" / "source_pdfs_abruzzo"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
POLY_CACHE_FILE = DATA_DIR / "abruzzo_polygons_cache.json"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-abruzzo.json"

PROVIDER_INFO = {
    "cam":   {"label": "CAM S.p.A.",          "ato": "ATO 2 — Marsica (AQ)",      "url": "https://www.camspa.com/"},
    "ruzzo": {"label": "Ruzzo Reti S.p.A.",   "ato": "ATO 5 — Teramano (TE)",      "url": "https://www.ruzzo.it/"},
    "aca":   {"label": "ACA S.p.A.",          "ato": "ATO 4 — Pescarese (PE)",     "url": "https://www.acaspa.it/"},
    "sasi":  {"label": "SASI S.p.A.",         "ato": "ATO 6 — Chietino (CH)",      "url": "https://www.sasispa.it/"},
}


# ---------- utils ----------
def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def load_cache() -> dict:
    if POLY_CACHE_FILE.exists():
        try:
            return json.loads(POLY_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(c: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POLY_CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


# ---------- comune name normalization ----------
def normalize_comune(raw: str) -> str:
    """Trasforma cose tipo 'avezzano_frazioni__Avezzano_frazioni' o
    'San_Salvo' in un nome leggibile 'Avezzano' / 'San Salvo'."""
    s = raw.replace("_frazioni", "")
    # Se c'è "__", la parte dopo è la versione "pretty"
    if "__" in s:
        s = s.split("__")[-1]
    s = s.replace("_", " ").strip()
    # Title case rispettando preposizioni
    parts = []
    for w in s.split():
        wl = w.lower()
        if wl in {"di", "da", "del", "della", "delle", "dei", "in", "su", "sul"}:
            parts.append(wl)
        elif wl.startswith("d'") or wl.startswith("l'"):
            parts.append(wl[:2] + wl[2:].capitalize())
        else:
            parts.append(wl.capitalize())
    return " ".join(parts)


# ---------- discovery per provider ----------
def discover_cam() -> list[dict]:
    out = []
    seen = set()
    for p in sorted((SRC_DIR / "CAM_spa").glob("*.pdf")):
        if "_frazioni" in p.stem:
            continue  # le frazioni hanno il file principale con stesso comune
        comune = normalize_comune(p.stem)
        if comune.lower() in seen:
            continue
        seen.add(comune.lower())
        out.append({"provider": "cam", "comune": comune, "pdf": p})
    return out


def _ruzzo_date(p: Path) -> str:
    """Estrae DDMMYY dal filename Ruzzo: 'n._XXXXXXX_del_DDMMYY__...'.
    Ritorna 'YYYY-MM-DD' o '0000-00-00' se non parsabile."""
    m = re.search(r"_del_(\d{2})(\d{2})(\d{2})", p.name)
    if not m:
        return "0000-00-00"
    dd, mm, yy = m.groups()
    yyyy = 2000 + int(yy)
    return f"{yyyy}-{mm}-{dd}"


def discover_ruzzo() -> list[dict]:
    base = SRC_DIR / "Ruzzo_Reti" / "2025"
    if not base.exists():
        return []
    out = []
    for d in sorted([x for x in base.iterdir() if x.is_dir()]):
        pdfs = list(d.glob("*.PDF")) + list(d.glob("*.pdf"))
        if not pdfs:
            continue
        # Più recente per data nel filename
        pdfs.sort(key=_ruzzo_date, reverse=True)
        best = pdfs[0]
        comune = normalize_comune(d.name)
        out.append({"provider": "ruzzo", "comune": comune, "pdf": best,
                    "n_reports": len(pdfs), "data": _ruzzo_date(best)})
    return out


def discover_aca() -> list[dict]:
    base = SRC_DIR / "ACA_Pescara" / "2026"
    if not base.exists():
        return []
    out = []
    for d in sorted([x for x in base.iterdir() if x.is_dir()]):
        # tutti i PDF "signed" nelle sub-cartelle (Sorgente/Serbatoio/...)
        cands = [p for p in d.rglob("*_signed.pdf")]
        if not cands:
            cands = list(d.rglob("*.pdf"))
        if not cands:
            continue
        # Preferenza: file con "Sorgente" nel path → fonte primaria
        sorgente = [p for p in cands if "Sorgente" in p.parts]
        chosen = sorted(sorgente)[0] if sorgente else sorted(cands)[0]
        comune = normalize_comune(d.name)
        out.append({"provider": "aca", "comune": comune, "pdf": chosen,
                    "n_reports": len(cands)})
    return out


_MESI_ORDER = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}


def discover_sasi() -> list[dict]:
    base = SRC_DIR / "SASI_spa" / "Dati Acqua 2026"
    if not base.exists():
        return []
    out = []
    for d in sorted([x for x in base.iterdir() if x.is_dir()]):
        # Struttura: <Comune>/Controlli Interni SASI SpA/<Mese>/*.pdf
        all_pdfs = list(d.rglob("*.pdf"))
        if not all_pdfs:
            continue
        # Sceglie il mese più recente disponibile (in ordine cronologico inverso)
        def _month_key(p: Path) -> int:
            for part in p.parts:
                m = _MESI_ORDER.get(part.lower())
                if m:
                    return m
            return 0
        all_pdfs.sort(key=_month_key, reverse=True)
        chosen = all_pdfs[0]
        comune = normalize_comune(d.name)
        out.append({"provider": "sasi", "comune": comune, "pdf": chosen,
                    "n_reports": len(all_pdfs)})
    return out


# ---------- geocoding ----------
_HEADERS = {"User-Agent": "AcquaMap-build/1.0 (acquamap-abruzzo)"}


def fetch_polygon(comune: str, provincia_hint: str | None = None) -> dict | None:
    """Ritorna {'geometry': ..., 'lat': ..., 'lon': ..., 'display_name': ...}
    oppure None. La geometry è MultiPolygon/Polygon Nominatim."""
    queries = []
    if provincia_hint:
        queries.append(f"{comune}, {provincia_hint}, Abruzzo, Italia")
    queries.append(f"{comune}, Abruzzo, Italia")
    for q in queries:
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": q,
                    "format": "json",
                    "polygon_geojson": 1,
                    "limit": 1,
                    "countrycodes": "it",
                    "addressdetails": 1,
                },
                headers=_HEADERS,
                timeout=15,
            )
            if r.status_code != 200:
                continue
            arr = r.json()
            if not arr:
                continue
            it = arr[0]
            geom = it.get("geojson")
            if not geom:
                continue
            t = (it.get("type") or "").lower()
            cls = (it.get("class") or "").lower()
            # Vogliamo solo amministrative (comune), non POI casuali
            ok_types = {"administrative", "city", "town", "village", "municipality", "hamlet"}
            if cls != "boundary" and cls != "place" and t not in ok_types:
                continue
            return {
                "geometry": geom,
                "lat": float(it["lat"]),
                "lon": float(it["lon"]),
                "display_name": it.get("display_name", ""),
            }
        except requests.RequestException:
            time.sleep(2)
            continue
    return None


PROV_HINTS = {
    "cam": "AQ",      # Marsica
    "ruzzo": "TE",    # Teramano
    "aca": "PE",      # Pescarese (alcuni CH/TE)
    "sasi": "CH",     # Chietino
}


# Alias manuali per nomi di comune storpiati nei filename dei provider.
# Chiave = slug normalizzato del nome estratto, valore = nome ufficiale.
COMUNE_ALIASES = {
    "civita_dantino": "Civita d'Antino",
    "massa_dalbe": "Massa d'Albe",
    "isola_del_gran_sasso": "Isola del Gran Sasso d'Italia",
    "montorio_potabilizzatore_montorio_colle_di_croce_uscita_finale": "Montorio al Vomano",
    "bussi": "Bussi sul Tirino",
    "fara_filorum_petri": "Fara Filiorum Petri",
    "casalguida": "Casalanguida",
    "castiglione_m_m": "Castiglione Messer Marino",
    "civitella_m_r": "Civitella Messer Raimondo",
    "montedorisio": "Monteodorisio",
    "san_martino_sulla_m": "San Martino sulla Marrucina",
    "schiavi_d_abruzzo": "Schiavi di Abruzzo",
    "magliano_dei_marsi": "Magliano de' Marsi",
}

# Slug che NON sono comuni (file spuri da escludere)
COMUNE_BLACKLIST = {
    "odichiarazionediaccessibiltdefinitiva",
}


# ---------- main ----------
def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] discovery PDF per provider…")
    entries: list[dict] = []
    entries += discover_cam()
    entries += discover_ruzzo()
    entries += discover_aca()
    entries += discover_sasi()

    by_prov: dict[str, int] = {}
    # Applica blacklist + alias
    filtered = []
    for e in entries:
        sl = slugify(e["comune"])
        if sl in COMUNE_BLACKLIST:
            continue
        if sl in COMUNE_ALIASES:
            e["comune"] = COMUNE_ALIASES[sl]
        filtered.append(e)
    entries = filtered
    for e in entries:
        by_prov[e["provider"]] = by_prov.get(e["provider"], 0) + 1
    for k, v in by_prov.items():
        print(f"   - {k:6s}  {v:3d} comuni")
    print(f"   totale: {len(entries)} entries")

    print("[2/4] geocoding poligoni (Nominatim, ~1s/comune)…")
    cache = load_cache()
    features = []
    skipped: list[tuple[str, str]] = []
    n_new = 0
    for i, e in enumerate(entries, 1):
        prov = e["provider"]
        comune = e["comune"]
        key = f"{prov}|{slugify(comune)}"
        info = cache.get(key)
        if info is None:
            hint = PROV_HINTS.get(prov)
            info = fetch_polygon(comune, hint)
            n_new += 1
            time.sleep(1.1)  # Nominatim rate limit
            cache[key] = info  # anche None viene cachato per evitare retry
            if n_new % 10 == 0:
                save_cache(cache)
        if not info:
            skipped.append((prov, comune))
            print(f"   ! [{i:3d}] {prov:6s} {comune:30s}  GEOCODE FAIL")
            continue
        slug = slugify(comune)
        feat_name = f"abruzzo_{prov}_{slug}"
        # Province dall'address Nominatim non sempre disponibile: usa hint
        info_prov_acr = PROV_HINTS.get(prov, "")
        feat = {
            "type": "Feature",
            "geometry": info["geometry"],
            "properties": {
                "name": feat_name,
                "comune": comune,
                "zona_label": None,
                "provincia_acr": info_prov_acr,
                "regione": "Abruzzo",
                "provider": f"abruzzo_{prov}",
                "provider_label": PROVIDER_INFO[prov]["label"],
                "provider_ato": PROVIDER_INFO[prov]["ato"],
                "lat": info["lat"],
                "lon": info["lon"],
            },
        }
        features.append(feat)

    save_cache(cache)
    print(f"   geocodificati: {len(features)}  /  skippati: {len(skipped)}")

    print("[3/4] copia PDF in data/pdfs/ …")
    for f in features:
        prov_short = f["properties"]["name"].split("_")[1]  # cam/ruzzo/...
        slug = "_".join(f["properties"]["name"].split("_")[2:])
        # ritrova l'entry originale
        entry = next(
            (e for e in entries
             if e["provider"] == prov_short and slugify(e["comune"]) == slug),
            None,
        )
        if not entry:
            continue
        dest = PDF_OUT_DIR / (f["properties"]["name"] + ".pdf")
        if dest.exists():
            continue
        try:
            shutil.copy2(entry["pdf"], dest)
        except Exception as exc:
            print(f"   ! copy fail {dest.name}: {exc}")

    print(f"[4/4] scrive {OUT_GEOJSON.name} …")
    fc = {"type": "FeatureCollection", "features": features,
          "_built_at": datetime.now(timezone.utc).isoformat()}
    OUT_GEOJSON.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"   OK  {len(features)} features")

    if skipped:
        print("\n[skipped] " + str(len(skipped)) + " comuni senza poligono:")
        for prov, com in skipped:
            print(f"   - {prov:6s} {com}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
