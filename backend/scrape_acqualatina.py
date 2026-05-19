"""
Scraper Acqualatina S.p.A. (ATO 4 — Lazio Meridionale, provincia di Latina).

Sito: https://www.acqualatina.it/qualita-dellacqua-per-comune/
Schema URL: la pagina indice contiene voci tipo
    download/valori-<slug>/?wpdmdl=<ID>
Il PDF reale si scarica via:
    https://www.acqualatina.it/?wpdmdl=<ID>

Operazioni:
  1. Scarica l'indice ed estrae (slug, wpdmdl_id) per ognuna delle 44 schede.
  2. Scarica ogni PDF in `backend/data/pdfs/acqualatina_<slug>.pdf`.
  3. Estrae il nome canonico del comune da ciascun PDF ("Comune di X").
  4. Genera `backend/data/mappa-qualita-acqualatina.json` filtrando il file
     ISTAT comuni Italia per i comuni serviti (poligono per ciascuna feature).
     Una feature per slug: si sovrappongono se più PDF condividono il comune
     base (es. anzio + anzio-2) — è il comportamento atteso, la tooltip
     distingue per `display_name` / `zona_label`.

Esecuzione:
    python backend/scrape_acqualatina.py
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pdfplumber  # type: ignore

ROOT = Path(__file__).parent / "data"
PDF_DIR = ROOT / "pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)
ISTAT_FILE = ROOT / "istat_comuni_italia.geojson"
OUT_GEOJSON = ROOT / "mappa-qualita-acqualatina.json"

INDEX_URL = "https://www.acqualatina.it/qualita-dellacqua-per-comune/"
DOWNLOAD_URL = "https://www.acqualatina.it/?wpdmdl={wid}"
UA = "Mozilla/5.0 (AcquaMap scraper)"

# Slug speciali che non si convertono banalmente in nome comune ISTAT.
SLUG_TO_COMUNE_OVERRIDE = {
    "villa-s-stefano": "Villa Santo Stefano",
    "santi-cosma-e-damiano": "Santi Cosma e Damiano",
    "s-s-cosma-e-damiano": "Santi Cosma e Damiano",
    "ss-cosma-e-damiano": "Santi Cosma e Damiano",
    "san-felice-circeo": "San Felice Circeo",
    "roccamassima": "Rocca Massima",
    "latina-nord": "Latina",
    "latina-sud": "Latina",
    "latina-borghi-nord": "Latina",
    "formia-centro-storico": "Formia",
    "gaeta-lungomare": "Gaeta",
    "aprilia-campoleone": "Aprilia",
    "maenza-2025": "Maenza",
}


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        return resp.read()


def fetch_index() -> dict[str, str]:
    """Ritorna {slug: wpdmdl_id} (deduplicato, primo ID per slug)."""
    html = _fetch(INDEX_URL).decode("utf-8", errors="ignore")
    pairs = re.findall(r"download/valori-([a-z0-9\-]+)/\?wpdmdl=(\d+)", html)
    out: dict[str, str] = {}
    for slug, wid in pairs:
        out.setdefault(slug, wid)
    return out


def _download_one(slug: str, wid: str) -> tuple[str, str]:
    dest = PDF_DIR / f"acqualatina_{slug}.pdf"
    if dest.exists() and dest.stat().st_size > 5000:
        return slug, "cached"
    data = _fetch(DOWNLOAD_URL.format(wid=wid))
    if len(data) < 2000 or not data.startswith(b"%PDF"):
        return slug, f"bad-pdf ({len(data)} bytes)"
    dest.write_bytes(data)
    return slug, f"ok ({len(data)} bytes)"


def download_all(index: dict[str, str]) -> None:
    print(f"[acqualatina] {len(index)} PDFs to download")
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(_download_one, s, w): s for s, w in index.items()}
        for i, fut in enumerate(as_completed(futs), 1):
            slug, status = fut.result()
            print(f"  [{i}/{len(index)}] {slug}: {status}")


def _norm(s: str) -> str:
    """Normalizza per match: rimuove accenti, lower, collassa spazi."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().lower()


def _extract_comune_from_pdf(pdf_path: Path) -> str | None:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            txt = pdf.pages[0].extract_text() or ""
    except Exception:
        return None
    m = re.search(r"Comune di\s+([^\n]+)", txt, re.IGNORECASE)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _slug_to_comune_guess(slug: str) -> str:
    """Conversione fallback: amaseno -> Amaseno, cisterna-di-latina -> Cisterna di Latina."""
    if slug in SLUG_TO_COMUNE_OVERRIDE:
        return SLUG_TO_COMUNE_OVERRIDE[slug]
    base = re.sub(r"-\d+$", "", slug)  # rimuove "-2" finale
    parts = base.split("-")
    # parole brevi (di, la, le, il, lo) restano minuscole; le altre title-case.
    minuscole = {"di", "la", "le", "il", "lo", "del", "della", "dei", "e", "al"}
    out = []
    for i, w in enumerate(parts):
        if i > 0 and w in minuscole:
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)


def build_geojson(index: dict[str, str]) -> None:
    print("[acqualatina] loading ISTAT comuni…")
    istat = json.loads(ISTAT_FILE.read_text(encoding="utf-8"))
    # Filtro: regione Lazio (per perf) e indicizza per nome normalizzato.
    by_name: dict[str, dict] = {}
    for feat in istat["features"]:
        p = feat.get("properties") or {}
        if p.get("reg_name") != "Lazio":
            continue
        by_name[_norm(p.get("name", ""))] = feat

    features: list[dict] = []
    missing: list[str] = []
    for slug in sorted(index):
        pdf_path = PDF_DIR / f"acqualatina_{slug}.pdf"
        comune = _extract_comune_from_pdf(pdf_path) if pdf_path.exists() else None
        if not comune:
            comune = _slug_to_comune_guess(slug)
        # Pulizia: rimuove eventuali specificazioni tra parentesi/trattini
        # (es. "Formia (Centro storico)" -> "Formia").
        comune_clean = re.sub(r"\s*[\(\-].*$", "", comune).strip()
        # Tenta nell'ordine: override esplicito, nome dal PDF (pulito), guess dallo slug.
        candidates = []
        if slug in SLUG_TO_COMUNE_OVERRIDE:
            candidates.append(SLUG_TO_COMUNE_OVERRIDE[slug])
        candidates.append(comune_clean)
        candidates.append(_slug_to_comune_guess(slug))
        istat_feat = None
        for cand in candidates:
            istat_feat = by_name.get(_norm(cand))
            if istat_feat:
                break
        if not istat_feat:
            missing.append(f"{slug} (comune={comune!r})")
            continue
        ip = istat_feat.get("properties") or {}
        # Etichetta zona: differenzia eventuali zone multiple ("anzio-2" -> "Zona 2").
        zona_suffix_m = re.search(r"-(\d+|[a-z]+)$", slug)
        zona_label = None
        if zona_suffix_m and slug.rsplit("-", 1)[0] in index:
            suffix = zona_suffix_m.group(1)
            zona_label = (
                f"Zona {suffix}" if suffix.isdigit() else suffix.capitalize()
            )
        elif comune != comune_clean:
            # PDF aveva specificazione (es. "Latina (Nord)" -> zona = "Nord")
            zlm = re.search(r"[\(\-]\s*([^\)\-]+?)\s*\)?$", comune)
            if zlm:
                zona_label = zlm.group(1).strip()

        feature = {
            "type": "Feature",
            "geometry": istat_feat.get("geometry"),
            "properties": {
                "name": f"acqualatina_{slug}",
                "comune": comune,
                "zona_label": zona_label,
                "link": f"https://www.acqualatina.it/?wpdmdl={index[slug]}",
                "wpdmdl": index[slug],
                "prov_acr": ip.get("prov_acr"),
                "prov_name": ip.get("prov_name"),
                "com_istat_code": ip.get("com_istat_code"),
            },
        }
        features.append(feature)

    geojson = {"type": "FeatureCollection", "features": features}
    OUT_GEOJSON.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    print(f"[acqualatina] wrote {OUT_GEOJSON} ({len(features)} features)")
    if missing:
        print(f"[acqualatina] {len(missing)} comuni without ISTAT polygon:")
        for m in missing:
            print(f"  ! {m}")


def main() -> int:
    if not ISTAT_FILE.exists():
        print(f"Missing {ISTAT_FILE}. Download openpolis ISTAT GeoJSON first.")
        return 1
    index = fetch_index()
    print(f"[acqualatina] index: {len(index)} entries")
    download_all(index)
    build_geojson(index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
