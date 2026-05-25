"""
build_campania.py
=================

Costruisce:
  - backend/data/mappa-qualita-campania.json   (GeoJSON poligoni)
  - backend/data/pdfs/campania_<provider>_<slug>.pdf

Provider supportati (cartella sorgente: backend/data/source_pdfs_campania/):
  - ABC_Napoli          → abc_napoli         (50 punti città di Napoli)
  - Acqua_Campania      → acqua_campania     (24 comuni/distretti, grossista)
  - Acquedotti_SCPA     → acquedotti_scpa    (8 comuni NA/CE multi-punto)
  - Alto_Calore         → alto_calore        (~129 comuni AV/BN/NA)
  - ASIS_Salernitana    → asis_salernitana   (~22 comuni SA multi-fontana)
  - Gesesa              → gesesa             (24 comuni/zone BN)
  - GORI                → gori               (75 comuni NA/SA)
  - ITL_spa             → itl_spa            (~50 comuni CE, multi-punto → latest)
  - Nepta_Acqua         → nepta_acqua        (29 punti città di Caserta)
  - Salerno_Sistemi     → salerno_sistemi    (45 quartieri di Salerno)
"""
from __future__ import annotations

import csv
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
SRC_DIR = HERE / "data" / "source_pdfs_campania"
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
POLY_CACHE_FILE = DATA_DIR / "campania_polygons_cache.json"
OUT_GEOJSON = DATA_DIR / "mappa-qualita-campania.json"

PROVIDER_INFO = {
    "abc_napoli":       {"label": "ABC Napoli S.p.A.",                       "ato": "ATO 2 — Napoli Volturno",     "url": "https://www.abc.napoli.it/"},
    "acqua_campania":   {"label": "Acqua Campania S.p.A.",                   "ato": "Adduzione regionale",          "url": "https://www.acquacampania.com/"},
    "acquedotti_scpa":  {"label": "Acquedotti S.C.p.A.",                     "ato": "Campania (NA/CE)",             "url": "https://www.acquedotti.com/"},
    "alto_calore":      {"label": "Alto Calore Servizi S.p.A.",              "ato": "ATO 1 — Calore Irpino",        "url": "https://www.altocalore.it/"},
    "asis_salernitana": {"label": "A.S.I.S. Salernitana Reti e Impianti S.p.A.", "ato": "ATO 4 — Sele",             "url": "https://www.asisspa.it/"},
    "gesesa":           {"label": "GESESA S.p.A.",                           "ato": "ATO 1 — Calore Irpino",        "url": "https://www.gesesa.it/"},
    "gori":             {"label": "GORI S.p.A.",                             "ato": "ATO 3 — Sarnese Vesuviano",    "url": "https://www.goriacqua.com/"},
    "itl_spa":          {"label": "I.T.L. S.p.A.",                           "ato": "ATO 2 — Napoli Volturno (CE)", "url": "https://www.itlspa.it/"},
    "nepta_acqua":      {"label": "Nepta Acqua S.r.l.",                      "ato": "Caserta (gestione locale)",    "url": ""},
    "salerno_sistemi":  {"label": "Salerno Sistemi S.p.A.",                  "ato": "ATO 4 — Sele",                 "url": "https://www.salernosistemi.it/"},
}

PROV_HINTS = {
    "abc_napoli":       "NA",
    "acqua_campania":   "CE",
    "acquedotti_scpa":  "NA",
    "alto_calore":      "AV",
    "asis_salernitana": "SA",
    "gesesa":           "BN",
    "gori":             "NA",
    "itl_spa":          "CE",
    "nepta_acqua":      "CE",
    "salerno_sistemi":  "SA",
}

# Provincia per ciascun comune Acquedotti_SCPA (cartella sorgente)
ACQUEDOTTI_SCPA_PROV = {
    "Acerra": "NA",
    "Alvignano": "CE",
    "Casandrino": "NA",
    "Castel_Morrone": "CE",
    "Grumo_Nevano": "NA",
    "Melito_di_Napoli": "NA",
    "Orta_di_Atella": "CE",
    "Qualiano": "NA",
}

# Distretti / aggregati di Acqua Campania → lista comuni reali
ACQUA_CAMPANIA_DISTRETTI = {
    "analisi-distretto-nord-est-crispano-caivano-cesa-frattaminore-succivo-marcianise-orta-di-atella":
        ("Distretto Nord-Est (Crispano-Caivano-Cesa-Frattaminore-Succivo-Marcianise-Orta di Atella)",
         ["Crispano", "Caivano", "Cesa", "Frattaminore", "Succivo", "Marcianise", "Orta di Atella"]),
    "analisi-distretto-nord-ovest-frignano-casaluce-carinaro-gricignano":
        ("Distretto Nord-Ovest (Frignano-Casaluce-Carinaro-Gricignano)",
         ["Frignano", "Casaluce", "Carinaro", "Gricignano di Aversa"]),
    "analisi-distretto-sud-est-s-arpino-frattamaggiore-santimo-grumo-nevano-casandrino":
        ("Distretto Sud-Est (Sant'Arpino-Frattamaggiore-Sant'Antimo-Grumo Nevano-Casandrino)",
         ["Sant'Arpino", "Frattamaggiore", "Sant'Antimo", "Grumo Nevano", "Casandrino"]),
    "analisi-distretto-sud-ovest-aversa-lusciano-parete-trentola":
        ("Distretto Sud-Ovest (Aversa-Lusciano-Parete-Trentola Ducenta)",
         ["Aversa", "Lusciano", "Parete", "Trentola-Ducenta"]),
    "analisi-interconnessione-arzano-porchiera-secondigliano":
        ("Interconnessione Arzano-Porchiera-Secondigliano",
         ["Arzano", "Napoli"]),
    "analisi-interconnessione-serbatoio-di-melito":
        ("Interconnessione Serbatoio di Melito",
         ["Melito di Napoli"]),
    "consegna-napoli-cupa-sfondata-dn-1800":
        ("Consegna Napoli — Cupa Sfondata DN 1800", ["Napoli"]),
    "consegna-napoli-cupa-sfondata-dn-2100":
        ("Consegna Napoli — Cupa Sfondata DN 2100", ["Napoli"]),
    "us-navy-gricignano":
        ("US Navy — Gricignano di Aversa", ["Gricignano di Aversa"]),
}

# Comuni di Acqua Campania fuori regione: serve disabilitare il vincolo
# "Campania, Italia" nella query Nominatim altrimenti il geocoding fallisce.
OUTSIDE_CAMPANIA = {
    "Sesto Campano": "IS",   # Molise
    "Cassino":       "FR",   # Lazio
    "Cervaro":       "FR",   # Lazio
}


# Comuni ASIS Salernitana noti (per parsing filename con underscore ambiguo)
# In ordine di lunghezza decrescente per match più lungo.
ASIS_COMUNI = [
    "Sant_Angelo_a_Fasanella",
    "Castelnuovo_di_Conza",
    "Pontecagnano_Faiano",
    "Contursi_Terme",
    "Roccadaspide",
    "Castelcivita",
    "Bellosguardo",
    "Trentinara",
    "Ricigliano",
    "Battipaglia",
    "Roccadaspide",
    "Castelcivita",
    "Bellosguardo",
    "Trentinara",
    "Ricigliano",
    "Perdifumo",
    "Torchiara",
    "Prignano",
    "Bellizzi",
    "Controne",
    "Colliano",
    "Agropoli",
    "Laureana",
    "Laviano",
    "Aquara",
    "Valva",
    "Serre",
    "Eboli",
]


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


def pretty_comune(s: str) -> str:
    s = s.replace("_", " ").replace("-", " ").strip()
    s = re.sub(r"\s+", " ", s)
    parts = []
    for w in s.split(" "):
        wl = w.lower()
        if wl in {"di", "da", "del", "della", "delle", "dei", "in", "su",
                  "sul", "a", "al", "alla", "e", "il", "lo", "la"}:
            parts.append(wl)
        elif wl.startswith("d'") or wl.startswith("l'"):
            parts.append(wl[:2] + wl[2:].capitalize())
        else:
            parts.append(wl.capitalize())
    out = " ".join(parts)
    # rimuovi suffisso provincia tipo " Av" / " Bn" / " Na"
    out = re.sub(r"\s+(Av|Bn|Na|Sa|Ce)\.?$", "", out)
    return out


def decode_html_entities(s: str) -> str:
    import html
    return html.unescape(s)


# ---------- discovery per provider ----------
def discover_abc_napoli() -> list[dict]:
    """ABC Napoli: 50 fontanelle/punti pubblici nel comune di Napoli.
    Filename: D01_Riviera_di_Chiaia.pdf → zona='Riviera di Chiaia', codice='D01'."""
    base = SRC_DIR / "ABC_Napoli"
    if not base.exists():
        return []
    out = []
    for p in sorted(base.glob("*.pdf")):
        stem = p.stem  # D01_Riviera_di_Chiaia
        stem = decode_html_entities(stem)
        m = re.match(r"^([A-Z]\d+)_(.+)$", stem)
        if m:
            codice, label = m.group(1), m.group(2)
        else:
            codice, label = stem[:3], stem
        zona_label = pretty_comune(label) + f" ({codice})"
        out.append({
            "provider": "abc_napoli",
            "comune": "Napoli",
            "zona_label": zona_label,
            "slug": slugify(f"{codice}_{label}"),
            "pdf": p,
        })
    return out


def discover_alto_calore() -> list[dict]:
    base = SRC_DIR / "Alto_Calore" / "Comuni"
    if not base.exists():
        return []
    out = []
    seen = set()
    for p in sorted(base.glob("*.pdf")):
        stem = p.stem  # Avellino-AV, Aiello-del-Sabato-AV
        m = re.match(r"^(.+)-(AV|BN|NA|SA|CE)$", stem)
        if m:
            raw_name, prov = m.group(1), m.group(2)
        else:
            raw_name, prov = stem, "AV"
        comune = pretty_comune(raw_name)
        key = (comune.lower(), prov)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "provider": "alto_calore",
            "comune": comune,
            "provincia": prov,
            "slug": slugify(comune),
            "pdf": p,
        })
    return out


def discover_gesesa() -> list[dict]:
    base = SRC_DIR / "Gesesa"
    if not base.exists():
        return []
    out = []
    seen = set()
    for p in sorted(base.glob("*.pdf")):
        stem = p.stem
        sl = slugify(stem)
        # Skip generic table
        if "tabella" in sl or "monitoraggio" in sl:
            continue
        if stem.upper().startswith("ZONA_"):
            # ZONA_1..ZONA_4 → sono frazioni/zone di Benevento città
            zona = stem.replace("_", " ").title()
            out.append({
                "provider": "gesesa",
                "comune": "Benevento",
                "zona_label": zona,
                "slug": slugify(f"benevento_{stem}"),
                "pdf": p,
            })
            continue
        comune = pretty_comune(stem)
        key = comune.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "provider": "gesesa",
            "comune": comune,
            "slug": slugify(comune),
            "pdf": p,
        })
    return out


def discover_gori() -> list[dict]:
    base = SRC_DIR / "GORI"
    if not base.exists():
        return []
    out = []
    seen = set()
    for p in sorted(base.glob("*.pdf")):
        stem = p.stem  # 00C01_ANACAPRI
        m = re.match(r"^\d+C\d+_(.+)$", stem)
        raw = m.group(1) if m else stem
        comune = pretty_comune(raw)
        key = comune.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "provider": "gori",
            "comune": comune,
            "slug": slugify(comune),
            "pdf": p,
        })
    return out


def _itl_date(p: Path) -> tuple[int, int, int]:
    """Estrae (anno, mese, giorno) da filename ITL '..._DD-MM-YY.pdf'."""
    m = re.search(r"_(\d{2})-(\d{2})-(\d{2,4})", p.name)
    if not m:
        return (0, 0, 0)
    dd, mm, yy = m.groups()
    y = int(yy)
    if y < 100:
        y += 2000
    return (y, int(mm), int(dd))


def discover_itl_spa() -> list[dict]:
    """ITL: 282 PDF (multi-punto per comune). Nome: COMUNE__COMUNE_PUNTO_DATA.pdf.
    Raggruppa per comune e tiene il più recente."""
    base = SRC_DIR / "ITL_spa"
    if not base.exists():
        return []
    by_comune: dict[str, list[Path]] = {}
    for p in sorted(base.glob("*.pdf")):
        # Prefix prima del doppio underscore = comune
        head = p.stem.split("__")[0]
        # Rimuovi suffissi tipo "_–_NITRATI" o " – NITRATI"
        head = re.sub(r"[_\s]+[–-][_\s]*NITRATI.*$", "", head, flags=re.IGNORECASE)
        comune = pretty_comune(head)
        by_comune.setdefault(comune, []).append(p)
    out = []
    for comune, pdfs in sorted(by_comune.items()):
        pdfs.sort(key=_itl_date, reverse=True)
        out.append({
            "provider": "itl_spa",
            "comune": comune,
            "slug": slugify(comune),
            "pdf": pdfs[0],
            "n_reports": len(pdfs),
        })
    return out


def discover_nepta_acqua() -> list[dict]:
    """Nepta: 29 PDF codici (A1, B1, ...) → tutti punti del comune di Caserta."""
    base = SRC_DIR / "Nepta_Acqua"
    if not base.exists():
        return []
    out = []
    for p in sorted(base.glob("*.pdf")):
        codice = p.stem.upper()
        out.append({
            "provider": "nepta_acqua",
            "comune": "Caserta",
            "zona_label": f"Punto {codice}",
            "slug": slugify(f"caserta_{codice}"),
            "pdf": p,
        })
    return out


def discover_salerno_sistemi() -> list[dict]:
    """Salerno Sistemi: 45 quartieri di Salerno (Quartieri/<name>.pdf).
    Usa _mapping_quartieri.csv per i nomi 'puliti' quando disponibile."""
    base = SRC_DIR / "Salerno_Sistemi" / "Quartieri"
    if not base.exists():
        return []
    # Carica mapping
    mapping: dict[str, str] = {}
    map_csv = SRC_DIR / "Salerno_Sistemi" / "_mapping_quartieri.csv"
    if map_csv.exists():
        try:
            with map_csv.open(encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    qname = (row.get("quartiere") or "").strip()
                    flocal = (row.get("file_locale") or "").strip()
                    if not qname or not flocal:
                        continue
                    fname = Path(flocal).name
                    mapping[fname] = qname
        except Exception:
            pass
    out = []
    for p in sorted(base.glob("*.pdf")):
        zona = mapping.get(p.name) or p.stem.replace("_", " ")
        zona = zona.strip()
        out.append({
            "provider": "salerno_sistemi",
            "comune": "Salerno",
            "zona_label": zona,
            "slug": slugify(f"salerno_{p.stem}"),
            "pdf": p,
        })
    return out


def _file_date(name: str) -> tuple[int, int, int]:
    """Estrae (anno, mese, giorno) da una stringa che contiene YYYY-MM-DD
    o YYYY_MM_DD o YYYY_MM (giorno=0). Ritorna (0,0,0) se non trovato."""
    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", name)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(20\d{2})[-_](\d{2})", name)
    if m:
        return (int(m.group(1)), int(m.group(2)), 0)
    m = re.search(r"(20\d{2})", name)
    if m:
        return (int(m.group(1)), 0, 0)
    return (0, 0, 0)


def discover_acquedotti_scpa() -> list[dict]:
    """Acquedotti S.C.p.A.: cartella per comune, dentro PDF multi-punto
    e multi-data nel pattern `YYYY_MM-Nome-Punto.pdf`. Per ogni (comune,
    punto) tiene il PDF più recente."""
    base = SRC_DIR / "Acquedotti_SCPA"
    if not base.exists():
        return []
    out: list[dict] = []
    for comune_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        comune = pretty_comune(comune_dir.name)
        prov = ACQUEDOTTI_SCPA_PROV.get(comune_dir.name, "NA")
        # Raggruppa per "nome punto" (filename senza la data iniziale)
        groups: dict[str, list[Path]] = {}
        for p in sorted(comune_dir.glob("*.pdf")):
            stem = p.stem
            # rimuove prefisso "YYYY_MM-" o "YYYY_MM_DD-"
            label = re.sub(r"^\d{4}[_-]\d{2}([_-]\d{2})?[-_]+", "", stem)
            label = label.replace("-", " ").replace("_", " ").strip()
            groups.setdefault(label, []).append(p)
        for label, pdfs in sorted(groups.items()):
            pdfs.sort(key=lambda p: _file_date(p.name), reverse=True)
            out.append({
                "provider": "acquedotti_scpa",
                "comune": comune,
                "provincia": prov,
                "zona_label": label,
                "slug": slugify(f"{comune}_{label}"),
                "pdf": pdfs[0],
                "n_reports": len(pdfs),
            })
    return out


def discover_acqua_campania() -> list[dict]:
    """Acqua Campania (grossista regionale): cartella per comune o per
    distretto/interconnessione/consegna. Per ogni cartella tiene il PDF
    più recente."""
    base = SRC_DIR / "Acqua_Campania"
    if not base.exists():
        return []
    out: list[dict] = []
    for sub in sorted(p for p in base.iterdir() if p.is_dir()):
        name = sub.name
        pdfs = sorted(sub.glob("*.pdf"), key=lambda p: _file_date(p.name),
                      reverse=True)
        if not pdfs:
            continue
        if name in ACQUA_CAMPANIA_DISTRETTI:
            zona_label, comuni = ACQUA_CAMPANIA_DISTRETTI[name]
            # Usa il primo comune della lista come "comune principale"
            # (per il geocoding fallback); il Voronoi userà tutti.
            comune = comuni[0]
            extra_comuni = comuni[1:] if len(comuni) > 1 else []
        elif name.startswith("analisi-comune-di-"):
            raw = name.removeprefix("analisi-comune-di-")
            comune = pretty_comune(raw)
            zona_label = ""
            extra_comuni = []
        else:
            comune = pretty_comune(name)
            zona_label = ""
            extra_comuni = []
        out.append({
            "provider": "acqua_campania",
            "comune": comune,
            "zona_label": zona_label,
            "slug": slugify(name),
            "pdf": pdfs[0],
            "n_reports": len(pdfs),
            "extra_comuni": extra_comuni,
        })
    return out


def discover_asis_salernitana() -> list[dict]:
    """A.S.I.S. Salernitana: 2492 PDF flat con pattern
    `26__NUMERO_Comune_Tipo_Indirizzo_YYYY-MM-DD.pdf`.
    Raggruppa per (numero punto, comune, indirizzo) e tiene il PDF più
    recente. Esempio:
      26__021_Battipaglia_Fontana_Piazza_Aldo_Moro_2025-02-19.pdf
        → comune='Battipaglia', tipo='Fontana',
          indirizzo='Piazza Aldo Moro', id=021
    """
    base = SRC_DIR / "ASIS_Salernitana"
    if not base.exists():
        return []
    # Re-sort: comuni più lunghi prima (per match greedy corretto).
    comuni_sorted = sorted(ASIS_COMUNI, key=len, reverse=True)
    # Regex precompilata
    re_main = re.compile(
        r"^26__(\d+)_(?P<rest>.+?)_(\d{4}-\d{2}-\d{2})$"
    )
    groups: dict[tuple, list[tuple[Path, tuple]]] = {}
    for p in sorted(base.glob("*.pdf")):
        stem = p.stem
        m = re_main.match(stem)
        if not m:
            continue
        codice = m.group(1)
        rest = m.group("rest")
        date_tuple = _file_date(stem)
        # Trova il comune nel `rest` (match più lungo)
        comune_key = None
        for c in comuni_sorted:
            if rest.startswith(c + "_") or rest == c:
                comune_key = c
                break
        if comune_key is None:
            # comune sconosciuto: prova fallback "primo token"
            tokens = rest.split("_")
            comune_key = tokens[0]
            after = "_".join(tokens[1:])
        else:
            after = rest[len(comune_key):].lstrip("_")
        # `after` ora è "Tipo_Indirizzo..." → tipo = primo token
        if not after:
            tipo, indirizzo = "Punto", ""
        else:
            tokens = after.split("_", 1)
            tipo = tokens[0]
            indirizzo = tokens[1] if len(tokens) > 1 else ""
        comune_pretty = pretty_comune(comune_key)
        indirizzo_pretty = indirizzo.replace("_", " ").strip()
        key = (codice, comune_pretty, indirizzo_pretty)
        groups.setdefault(key, []).append((p, date_tuple, tipo))
    out: list[dict] = []
    for (codice, comune, indirizzo), items in sorted(groups.items()):
        items.sort(key=lambda t: t[1], reverse=True)
        pdf_latest, _, tipo = items[0]
        zona_label = (f"{tipo} {indirizzo}".strip()
                      if indirizzo else tipo)
        zona_label = f"{zona_label} ({codice})"
        out.append({
            "provider": "asis_salernitana",
            "comune": comune,
            "provincia": "SA",
            "zona_label": zona_label,
            "slug": slugify(f"asis_{codice}_{comune}_{indirizzo}"),
            "pdf": pdf_latest,
            "n_reports": len(items),
        })
    return out


# ---------- geocoding ----------
_HEADERS = {"User-Agent": "AcquaMap-build/1.0 (acquamap-campania)"}
_MISSING = object()


def fetch_polygon(
    comune: str,
    provincia_hint: str | None = None,
    *,
    area_hint: str | None = None,
    allow_point: bool = False,
    region: str | None = "Campania",
) -> dict | None:
    """Geocodifica comune (o quartiere/strada se passato come `comune`).
    - `area_hint`: contesto aggiuntivo es. "Salerno" per i quartieri.
    - `allow_point`: se True, accetta anche geometrie Point (es. indirizzi
      stradali, fontanelle, punti di prelievo).
    - `region`: regione amministrativa per restringere la query
      (default "Campania"). Passa None per cercare in tutta Italia
      (necessario per i comuni di Acqua Campania fuori regione:
      Sesto Campano/IS, Cassino/FR, Cervaro/FR).
    """
    queries: list[str] = []
    region_suffix = f", {region}, Italia" if region else ", Italia"
    # Prima: query stretta senza area_hint (più precisa per strade/highway)
    if provincia_hint:
        queries.append(f"{comune}, {provincia_hint}{region_suffix}")
    queries.append(f"{comune}{region_suffix}")
    # Poi: query con area_hint (utile per quartieri ambigui es. "Fratte" -> "Fratte, Salerno")
    if area_hint and provincia_hint:
        queries.append(f"{comune}, {area_hint}, {provincia_hint}{region_suffix}")
    if area_hint:
        queries.append(f"{comune}, {area_hint}{region_suffix}")
    for q in queries:
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": q, "format": "json", "polygon_geojson": 1,
                    "limit": 5, "countrycodes": "it", "addressdetails": 1,
                },
                headers=_HEADERS,
                timeout=15,
            )
            if r.status_code != 200:
                print(f"     ! Nominatim HTTP {r.status_code} q={q!r}")
                time.sleep(3)
                continue
            try:
                arr = r.json()
            except (ValueError, requests.exceptions.JSONDecodeError):
                print(f"     ! Nominatim non-JSON (rate?) q={q!r} body[:80]={r.text[:80]!r}")
                time.sleep(5)
                continue
            if not arr:
                continue
            ok_types = {"administrative", "city", "town", "village",
                        "municipality", "hamlet", "suburb", "neighbourhood",
                        "quarter", "residential"}
            # Quando stiamo cercando una zona DENTRO un comune (area_hint),
            # non vogliamo che Nominatim ci restituisca il comune intero.
            exclude_municipal = bool(area_hint)
            municipal_types = {"city", "town", "municipality", "administrative"}
            # Pass 1: cerca un poligono
            for it in arr:
                geom = it.get("geojson")
                if not geom:
                    continue
                gtype = (geom.get("type") or "")
                # In pass 1 vogliamo solo aree (Polygon/MultiPolygon).
                # Punti e linee (strade) vengono provati solo in pass 2.
                if gtype not in ("Polygon", "MultiPolygon"):
                    continue
                t = (it.get("type") or "").lower()
                cls = (it.get("class") or "").lower()
                if (cls not in ("boundary", "place")
                        and t not in ok_types
                        and cls != "highway"):
                    continue
                # Scarta il poligono del comune stesso quando cerchiamo una zona
                if exclude_municipal and t in municipal_types and cls == "boundary":
                    continue
                return {
                    "geometry": geom,
                    "lat": float(it["lat"]),
                    "lon": float(it["lon"]),
                    "display_name": it.get("display_name", ""),
                }
            # Pass 2 (solo se richiesto): accetta Point
            if allow_point:
                for it in arr:
                    geom = it.get("geojson")
                    if not geom:
                        continue
                    if (geom.get("type") or "") != "Point":
                        continue
                    t = (it.get("type") or "").lower()
                    if exclude_municipal and t in municipal_types:
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


# Alias manuali (slug → nome ufficiale)
COMUNE_ALIASES = {
    "sant_agata_de_goti": "Sant'Agata de' Goti",
    "sant_anastasia": "Sant'Anastasia",
    "sant_antonio_abate": "Sant'Antonio Abate",
    "sant_agnello": "Sant'Agnello",
    "sant_egidio_del_monte_albino": "Sant'Egidio del Monte Albino",
    "santa_maria_la_carita": "Santa Maria la Carità",
    "pomigliano_d_arco": "Pomigliano d'Arco",
    "castel_baronia": "Castel Baronia",
    "capriglia_irpina": "Capriglia Irpina",
    "san_demetrio_ne_vestini": "San Demetrio ne' Vestini",
    "santo_stefano_di_sessanio": "Santo Stefano di Sessanio",
    "santa_maria_a_vico": "Santa Maria a Vico",
    "santa_maria_la_fossa": "Santa Maria la Fossa",
    "san_felice_a_cancello": "San Felice a Cancello",
    "san_marco_evangelista": "San Marco Evangelista",
    "san_nicola_la_strada": "San Nicola la Strada",
    "san_potito_sannitico": "San Potito Sannitico",
    "san_marcellino": "San Marcellino",
    "torre_del_greco": "Torre del Greco",
    "torre_annunziata": "Torre Annunziata",
    "tora_e_piccilli": "Tora e Piccilli",
    "vairano_patenora": "Vairano Patenora",
    "vairano_panterona": "Vairano Patenora",
    "villa_di_briano": "Villa di Briano",
    "conca_della_campania": "Conca della Campania",
    "castel_campagnano": "Castel Campagnano",
    "castel_volturno": "Castel Volturno",
    "piana_di_monte_verna": "Piana di Monte Verna",
    "portico_di_caserta": "Portico di Caserta",
    "pignataro_maggiore": "Pignataro Maggiore",
    "macerata_campania": "Macerata Campania",
    "marzano_appio": "Marzano Appio",
    "giano_vetusto": "Giano Vetusto",
    "tocco_caudio": "Tocco Caudio",
    "torrecuso": "Torrecuso",
    "frasso_telesino": "Frasso Telesino",
    "foiano_di_val_fortore": "Foiano di Val Fortore",
    "colle_sannita": "Colle Sannita",
    "telese_terme": "Telese Terme",
    "san_bartolomeo_in_galdo": "San Bartolomeo in Galdo",
    "riado": "Riardo",
    "ariano_irpino": "Ariano Irpino",
    "altavilla_irpina": "Altavilla Irpina",
    "cassano_irpino": "Cassano Irpino",
    "castelvetere_sul_calore": "Castelvetere sul Calore",
    "chiusano_san_domenico": "Chiusano San Domenico",
    "aiello_del_sabato": "Aiello del Sabato",
    "ospedaletto_dalpinolo": "Ospedaletto d'Alpinolo",
    "prata_principato_ultra": "Prata di Principato Ultra",
    "chiusano_san_domenico": "Chiusano di San Domenico",
    "santandrea_di_conza": "Sant'Andrea di Conza",
    "santangelo_a_cupolo": "Sant'Angelo a Cupolo",
    "santangelo_a_scala": "Sant'Angelo a Scala",
    "santangelo_allesca": "Sant'Angelo all'Esca",
    "santangelo_dei_lombardi": "Sant'Angelo dei Lombardi",
    "santarcangelo_trimonte": "Sant'Arcangelo Trimonte",
}


def _voronoi_tessellate_provider(
        features: list[tuple[dict, dict]],
        cache: dict,
        prov_key: str,
        comune_name: str) -> None:
    """Sostituisce la geometry di ogni feature del provider con la cella
    Voronoi corrispondente, clippata al confine del comune. Garantisce
    poligoni adiacenti che coprono il comune senza sovrapposizioni."""
    from shapely.geometry import (
        MultiPoint, Point as SPoint, shape, mapping)
    from shapely.ops import voronoi_diagram, unary_union

    target_prov = f"campania_{prov_key}"
    # Per provider sparsi su pi\u00f9 comuni (ASIS, SCPA), filtra anche per
    # comune: il Voronoi deve essere fatto separatamente per ogni
    # tessellatura comunale.
    subset = [(f, e) for (f, e) in features
              if f["properties"].get("provider") == target_prov
              and (prov_key in ("abc_napoli", "salerno_sistemi")
                   or f["properties"].get("comune") == comune_name)]
    if len(subset) < 2:
        return
    cache_key = f"{slugify(comune_name)}|{PROV_HINTS.get(prov_key, '')}"
    comune_info = cache.get(cache_key)
    if not comune_info or not comune_info.get("geometry"):
        print(f"   ! Voronoi {prov_key}: manca poligono comune in cache")
        return
    boundary = shape(comune_info["geometry"])
    if not boundary.is_valid:
        boundary = boundary.buffer(0)
    # Deduplica i seed coincidenti (Voronoi non gestisce punti duplicati):
    # se due feature hanno lat/lon identici, sposta leggermente il secondo.
    seen: dict[tuple, int] = {}
    seeds: list[tuple[float, float]] = []
    for f, _ in subset:
        lon = float(f["properties"]["lon"])
        lat = float(f["properties"]["lat"])
        key = (round(lon, 6), round(lat, 6))
        if key in seen:
            seen[key] += 1
            # sposta di ~50m in cerchio attorno
            import math as _math
            ang = seen[key] * 2.39996  # spirale a golden angle
            r = 0.0006 * (1 + seen[key] / 10)
            lon += r * _math.cos(ang)
            lat += r * _math.sin(ang)
        else:
            seen[key] = 0
        seeds.append((lon, lat))
    pts = [SPoint(x, y) for x, y in seeds]
    mp = MultiPoint(pts)
    envelope = boundary.buffer(0.15).envelope
    vd = voronoi_diagram(mp, envelope=envelope)
    cells = list(vd.geoms)
    # Associa ogni cella al seed che la genera (covers); fallback distanza.
    n_clipped = 0
    for (f, _), p in zip(subset, pts):
        chosen = None
        for c in cells:
            if c.covers(p):
                chosen = c
                break
        if chosen is None:
            chosen = min(cells, key=lambda c: c.distance(p))
        clipped = chosen.intersection(boundary)
        if clipped.is_empty or clipped.area == 0:
            # micro-buffer di sicurezza (caso patologico: seed fuori boundary)
            clipped = p.buffer(0.0008).intersection(boundary)
            if clipped.is_empty:
                clipped = p.buffer(0.0008)
        if clipped.geom_type == "GeometryCollection":
            polys = [g for g in clipped.geoms
                     if g.geom_type in ("Polygon", "MultiPolygon")]
            clipped = unary_union(polys) if polys else p.buffer(0.0008)
        f["geometry"] = mapping(clipped)
        n_clipped += 1
    print(f"   Voronoi {prov_key}: {n_clipped} celle clippate "
          f"({comune_name})")


def main() -> int:
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] discovery PDF per provider…")
    entries: list[dict] = []
    entries += discover_abc_napoli()
    entries += discover_acqua_campania()
    entries += discover_acquedotti_scpa()
    entries += discover_alto_calore()
    entries += discover_asis_salernitana()
    entries += discover_gesesa()
    entries += discover_gori()
    entries += discover_itl_spa()
    entries += discover_nepta_acqua()
    entries += discover_salerno_sistemi()

    # Applica alias
    for e in entries:
        sl = slugify(e["comune"])
        if sl in COMUNE_ALIASES:
            e["comune"] = COMUNE_ALIASES[sl]

    by_prov: dict[str, int] = {}
    for e in entries:
        by_prov[e["provider"]] = by_prov.get(e["provider"], 0) + 1
    for k, v in sorted(by_prov.items()):
        print(f"   - {k:18s} {v:4d} entries")
    print(f"   totale: {len(entries)} entries")

    print("[2/4] geocoding poligoni (Nominatim, cache)…")
    cache = load_cache()
    features = []
    skipped: list[tuple[str, str]] = []
    n_new = 0
    for i, e in enumerate(entries, 1):
        prov = e["provider"]
        comune = e["comune"]
        zona_label = e.get("zona_label")
        info = None

        # ----- Strategie speciali per provider con molti PDF in un solo comune -----
        # ABC Napoli (50 punti dentro Napoli) → geocodifica la strada/zona come
        # Point cosicchè ogni prelievo sia un segnaposto puntuale.
        # Salerno Sistemi (45 quartieri di Salerno) → cerca prima il quartiere
        # come boundary/suburb; fallback al poligono comunale.
        if prov in ("abc_napoli", "salerno_sistemi",
                    "asis_salernitana", "acquedotti_scpa") and zona_label:
            # Pulisci "(D01)", "(Q12)" ecc. dal label per la query
            zona_query = re.sub(r"\s*\([A-Z]?\d+\)\s*$", "", zona_label).strip()
            zona_key = f"{slugify(comune)}|zona|{slugify(zona_query)}"
            # Se in cache ma None (fallita in passato per rate limit), riprova.
            cached = cache.get(zona_key, _MISSING)
            if cached is _MISSING or cached is None:
                hint = e.get("provincia") or PROV_HINTS.get(prov)
                # Accetta anche Point per entrambi: per ABC Napoli sono
                # indirizzi stradali, per Salerno Sistemi sono quartieri
                # spesso mappati solo come nodo in OSM.
                info = fetch_polygon(
                    zona_query,
                    hint,
                    area_hint=comune,
                    allow_point=True,
                )
                n_new += 1
                time.sleep(2.5)
                cache[zona_key] = info
                if n_new % 10 == 0:
                    save_cache(cache)
            else:
                info = cached

        # Fallback (sia per gli altri provider che per ABC/Salerno se zona
        # non trovata): poligono comunale, cached per comune.
        if info is None:
            cache_key = f"{slugify(comune)}|{PROV_HINTS.get(prov,'')}"
            info = cache.get(cache_key)
            if info is None:
                hint = e.get("provincia") or PROV_HINTS.get(prov)
                # Comuni fuori Campania (solo Acqua Campania): override
                # provincia e disabilita vincolo regionale.
                if comune in OUTSIDE_CAMPANIA:
                    hint = OUTSIDE_CAMPANIA[comune]
                    info = fetch_polygon(comune, hint, region=None)
                else:
                    info = fetch_polygon(comune, hint)
                n_new += 1
                time.sleep(1.5)
                cache[cache_key] = info
                if n_new % 10 == 0:
                    save_cache(cache)
            # Per ABC Napoli e Salerno Sistemi NON renderizzare lo stesso
            # poligono comunale per 10/40 prelievi (creerebbe sovrapposizioni
            # opache che coprono i Point dei quartieri). Convertilo in Point
            # con jitter deterministico basato sul nome zona.
            if (info is not None
                    and prov in ("abc_napoli", "salerno_sistemi",
                                 "asis_salernitana",
                                 "acquedotti_scpa")):
                gt = (info.get("geometry") or {}).get("type")
                if gt in ("Polygon", "MultiPolygon"):
                    import hashlib as _hashlib
                    seed = (e.get("slug") or zona_label or "").encode("utf-8")
                    h = _hashlib.md5(seed).hexdigest()
                    # jitter ~±0.006° ≈ ±650m (sufficiente per separare
                    # visivamente i prelievi dentro lo stesso comune)
                    dx = (int(h[0:4], 16) / 0xffff - 0.5) * 0.012
                    dy = (int(h[4:8], 16) / 0xffff - 0.5) * 0.012
                    new_lat = info["lat"] + dy
                    new_lon = info["lon"] + dx
                    info = {
                        "geometry": {
                            "type": "Point",
                            "coordinates": [new_lon, new_lat],
                        },
                        "lat": new_lat,
                        "lon": new_lon,
                        "display_name": info.get("display_name", ""),
                    }
        if not info:
            skipped.append((prov, comune))
            print(f"   ! [{i:4d}] {prov:18s} {comune:30s}  GEOCODE FAIL")
            continue
        slug = e["slug"]
        feat_name = f"campania_{prov}_{slug}"
        feat = {
            "type": "Feature",
            "geometry": info["geometry"],
            "properties": {
                "name": feat_name,
                "comune": comune,
                "zona_label": e.get("zona_label"),
                "provincia_acr": e.get("provincia") or PROV_HINTS.get(prov, ""),
                "regione": "Campania",
                "provider": f"campania_{prov}",
                "provider_label": PROVIDER_INFO[prov]["label"],
                "provider_ato": PROVIDER_INFO[prov]["ato"],
                "lat": info["lat"],
                "lon": info["lon"],
            },
        }
        features.append((feat, e))

    save_cache(cache)
    print(f"   geocodificati: {len(features)}  /  skippati: {len(skipped)}")

    # ----- Voronoi tassellazione per ABC Napoli e Salerno Sistemi -----
    # Tutti i prelievi di questi provider sono concentrati in un singolo
    # comune (Napoli / Salerno) e fino ad ora venivano resi come Point o
    # LineString. L'utente vuole invece poligoni adiacenti che dividano
    # il territorio comunale senza sovrapposizioni: applico un Voronoi
    # sui seed (lat/lon) clippato al confine del comune.
    try:
        _voronoi_tessellate_provider(
            features, cache, "abc_napoli", "Napoli")
        _voronoi_tessellate_provider(
            features, cache, "salerno_sistemi", "Salerno")
        # ASIS e Acquedotti SCPA hanno più prelievi per comune sparsi su
        # comuni diversi: applica Voronoi separatamente per ogni comune
        # che abbia almeno 2 feature.
        for multi_prov in ("asis_salernitana", "acquedotti_scpa"):
            target_prov = f"campania_{multi_prov}"
            comuni_set: dict[str, int] = {}
            for f, _ in features:
                if f["properties"].get("provider") == target_prov:
                    cn = f["properties"].get("comune") or ""
                    comuni_set[cn] = comuni_set.get(cn, 0) + 1
            for cn, n in sorted(comuni_set.items()):
                if n < 2:
                    continue
                # Pre-fetch boundary del comune se manca in cache
                ck = f"{slugify(cn)}|{PROV_HINTS.get(multi_prov, '')}"
                if not cache.get(ck) or not cache[ck].get("geometry") \
                        or cache[ck]["geometry"].get("type") == "Point":
                    # Trova provincia dal primo entry di quel comune
                    prov_hint = PROV_HINTS.get(multi_prov, "")
                    for f, e in features:
                        if (f["properties"].get("provider") == target_prov
                                and f["properties"].get("comune") == cn):
                            prov_hint = (f["properties"].get("provincia_acr")
                                         or prov_hint)
                            break
                    bnd = fetch_polygon(cn, prov_hint)
                    time.sleep(1.5)
                    if bnd and bnd.get("geometry", {}).get("type") \
                            in ("Polygon", "MultiPolygon"):
                        cache[ck] = bnd
                        save_cache(cache)
                _voronoi_tessellate_provider(
                    features, cache, multi_prov, cn)
    except Exception as exc:
        print(f"   ! Voronoi fallito: {exc}")

    # ----- Post-process: forza ogni Point/LineString a diventare un
    # poligono. Sostituisce con il poligono del comune di appartenenza
    # (recuperato dalla cache o geocodificato ex-novo se mancante).
    n_forced = 0
    for f, e in features:
        gt = (f["geometry"] or {}).get("type")
        if gt in ("Polygon", "MultiPolygon"):
            continue
        prov_key = f["properties"]["provider"].replace("campania_", "", 1)
        cn = f["properties"].get("comune") or ""
        prov_hint = (f["properties"].get("provincia_acr")
                     or PROV_HINTS.get(prov_key, ""))
        ck = f"{slugify(cn)}|{PROV_HINTS.get(prov_key, '')}"
        info = cache.get(ck)
        if (not info
                or (info.get("geometry") or {}).get("type")
                not in ("Polygon", "MultiPolygon")):
            # Geocodifica ex-novo (region=None per comuni fuori-Campania)
            region = None if cn in OUTSIDE_CAMPANIA else "Campania"
            hint = (OUTSIDE_CAMPANIA.get(cn) or prov_hint)
            info = fetch_polygon(cn, hint, region=region)
            time.sleep(1.5)
            if info and (info.get("geometry") or {}).get("type") \
                    in ("Polygon", "MultiPolygon"):
                cache[ck] = info
        if info and (info.get("geometry") or {}).get("type") \
                in ("Polygon", "MultiPolygon"):
            f["geometry"] = info["geometry"]
            n_forced += 1
        else:
            print(f"   ! impossibile forzare a poligono: "
                  f"{f['properties']['provider']} / {cn}")
    if n_forced:
        save_cache(cache)
        print(f"   forzati a poligono: {n_forced} feature non-area")

    print("[3/4] copia PDF in data/pdfs/ …")
    for feat, entry in features:
        dest = PDF_OUT_DIR / (feat["properties"]["name"] + ".pdf")
        if dest.exists():
            continue
        try:
            shutil.copy2(entry["pdf"], dest)
        except Exception as exc:
            print(f"   ! copy fail {dest.name}: {exc}")

    print(f"[4/4] scrive {OUT_GEOJSON.name} …")
    fc = {"type": "FeatureCollection",
          "features": [f for f, _ in features],
          "_built_at": datetime.now(timezone.utc).isoformat()}
    OUT_GEOJSON.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"   OK  {len(features)} features")

    if skipped:
        print(f"\n[skipped] {len(skipped)} comuni senza poligono:")
        for prov, com in skipped:
            print(f"   - {prov:18s} {com}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
