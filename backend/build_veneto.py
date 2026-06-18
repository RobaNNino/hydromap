"""
Build runtime data per i gestori idrici del Veneto e del Friuli-Venezia Giulia.

Integra 11 gestori in un colpo solo (un GeoJSON ciascuno + i PDF runtime):

  Standalone (cartelle <provider>_pdf, una scheda per comune/zona)
    - ags             Azienda Gardesana Servizi (Garda veronese)
    - mediochiampo    Medio Chiampo (Vicenza, valle del Chiampo)
    - piaveservizi    Piave Servizi (Treviso)
    - gruppoveritas   Veritas (Venezia)

  Scrape "in pagina" (backend/inpage_water_quality, guidato dai CSV)
    - acquevenete     Acque Venete (RO/PD)
    - acqueveronesi   Acque Veronesi (VR)
    - lta             LTA (Pordenone/Veneto orientale)
    - sibspa          SIB (Belluno)
    - viacqua         Viacqua (Vicenza)
    - acquedelchiampo Acque del Chiampo (Vicenza)
    - acegasapsamga   AcegasApsAmga (Padova/Trieste, gruppo Hera)

Poligoni: un poligono comunale ISTAT per (gestore, comune). I gestori "in
pagina" hanno spesso decine di punti per comune: per non gonfiare il payload
servito da Render (piano free, 512MB) si tiene UN solo PDF rappresentativo per
comune. Le geometrie comunali vengono semplificate (Douglas-Peucker) per
alleggerire la geojson-cache.

Output per ogni provider <p>:
  - backend/data/mappa-qualita-<p>.json
  - backend/data/pdfs/<p>_<comune>_<hash>.pdf   (PDF rappresentativo)
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
from shapely.geometry import shape, mapping, Point

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
PDF_OUT_DIR = DATA_DIR / "pdfs"
ISTAT_GEOJSON = DATA_DIR / "istat_comuni_italia.geojson"
INPAGE_DIR = HERE / "inpage_water_quality"

MAX_FEATURE_NAME_LEN = 80
SIMPLIFY_TOL = 0.0006  # ~60 m: poligoni comunali leggeri per la cache

# Regioni da indicizzare per il matching del comune. Tutti questi gestori
# operano in Veneto/FVG: restringere l'indice riduce gli omonimi e i falsi
# positivi del matching per prefisso.
REGIONS_PRIMARY = ("Veneto", "Friuli-Venezia Giulia")
REGIONS_BORDER = ()

# Comuni soppressi/fusi o con abbreviazioni non risolvibili automaticamente.
ALIASES = {
    "grancona": "val liona",          # fusione 2017 in Val Liona (VI)
    "cornedo vic": "cornedo vicentino",
    "fara vic no": "fara vicentino",
    "fara vic": "fara vicentino",
    "isola vic": "isola vicentina",
    "marano vic": "marano vicentino",
}


# ----------------------------------------------------------------------------
# normalizzazione / slug
# ----------------------------------------------------------------------------
def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def slugify(s: str) -> str:
    s = _strip_accents(s).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:150]


def short_feature_name(prefix: str, label: str, seed: str) -> str:
    slug = slugify(label)
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    room = MAX_FEATURE_NAME_LEN - len(prefix) - len(digest) - 2
    head = slug[:max(8, room)].strip("_")
    return f"{prefix}_{head}_{digest}"


def _norm(s: str) -> str:
    """Normalizza un nome di comune per il matching."""
    s = _strip_accents(str(s or "")).lower()
    s = s.replace("'", " ").replace("`", " ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _title(s: str) -> str:
    out = s.title()
    return re.sub(r"\b(Di|Del|Della|Delle|Dei|Degli|Da|De|E|Sul|Sue|In|A)\b",
                  lambda m: m.group(1).lower(), out)


# ----------------------------------------------------------------------------
# indice comuni ISTAT + matching
# ----------------------------------------------------------------------------
class ComuneIndex:
    def __init__(self) -> None:
        self.by_norm: dict[str, dict] = {}
        self.keys: list[str] = []
        self._shapes: list[tuple] | None = None  # (key, bbox, geom)

    def add(self, props: dict, geom: dict, primary: bool) -> None:
        name = props.get("name") or ""
        key = _norm(name)
        if not key:
            return
        # primari hanno precedenza sui comuni di confine omonimi
        if key in self.by_norm and not primary:
            return
        self.by_norm[key] = {
            "name": name,
            "provincia": props.get("prov_name") or "",
            "prov_acr": props.get("prov_acr") or "",
            "regione": props.get("reg_name") or "",
            "geometry": geom,
        }

    def finalize(self) -> None:
        self.keys = sorted(self.by_norm.keys())

    def _candidates(self, raw: str) -> list[str]:
        """Genera varianti normalizzate da provare (abbreviazioni S./Vic.)."""
        base = _norm(raw)
        cands = [base, ALIASES.get(base, base)]
        toks = base.split()
        # espandi 's' / 'ss' iniziale o isolato -> San/Santa/...
        for i, t in enumerate(toks):
            if t in ("s", "ss", "st"):
                for repl in ("san", "santa", "santo", "santi", "sant"):
                    cands.append(" ".join(toks[:i] + [repl] + toks[i + 1:]))
            # 'vic'/'vic no' -> vicentino/vicentina
            if t == "vic":
                tail = toks[i + 1:]
                if tail[:1] == ["no"]:
                    tail = tail[1:]
                for repl in ("vicentino", "vicentina"):
                    cands.append(" ".join(toks[:i] + [repl] + tail))
        seen, out = set(), []
        for c in cands:
            c = c.strip()
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def match(self, raw: str) -> dict | None:
        for cand in self._candidates(raw):
            hit = self._match_one(cand)
            if hit:
                return hit
        return None

    def match_point(self, lat: float, lon: float) -> dict | None:
        """Comune contenente il punto (lat, lon) — point-in-polygon."""
        if self._shapes is None:
            self._shapes = []
            for key, v in self.by_norm.items():
                try:
                    g = shape(v["geometry"])
                    self._shapes.append((key, g.bounds, g))
                except Exception:
                    continue
        pt = Point(lon, lat)
        for key, (minx, miny, maxx, maxy), g in self._shapes:
            if minx <= lon <= maxx and miny <= lat <= maxy and g.contains(pt):
                return self.by_norm[key]
        return None

    def _match_one(self, q: str) -> dict | None:
        if not q:
            return None
        # 1) esatto (anche nomi corti tipo "vo")
        if q in self.by_norm:
            return self.by_norm[q]
        if len(q) < 4:
            return None
        # 2) un comune e' prefisso-a-parole di q (es. "caorle centro storico" -> caorle)
        best = None
        for k in self.keys:
            if q.startswith(k + " ") and (best is None or len(k) > len(best)):
                best = k
        if best:
            return self.by_norm[best]
        # 3) q e' prefisso-a-parole di un comune (es. "san pietro di f" -> ...feletto)
        pref = [k for k in self.keys if k.startswith(q + " ")]
        if len(pref) == 1:
            return self.by_norm[pref[0]]
        # 4) q e' prefisso-di-carattere unico (es. "vittorio v" -> vittorio veneto,
        #    "mareno di p" -> mareno di piave). Richiede q abbastanza lungo.
        if len(q) >= 6:
            charpref = [k for k in self.keys if k.startswith(q)]
            if len(charpref) == 1:
                return self.by_norm[charpref[0]]
            if pref:
                pref.sort(key=len)
                return self.by_norm[pref[0]]
        # 5) close match
        import difflib
        m = difflib.get_close_matches(q, self.keys, n=1, cutoff=0.88)
        if m:
            return self.by_norm[m[0]]
        return None


_SIMPLIFY_CACHE: dict[str, dict] = {}


def _simplify(comune_key: str, geom: dict) -> dict:
    if comune_key in _SIMPLIFY_CACHE:
        return _SIMPLIFY_CACHE[comune_key]
    try:
        g = shape(geom).buffer(0).simplify(SIMPLIFY_TOL, preserve_topology=True)
        out = mapping(g) if not g.is_empty else geom
    except Exception:
        out = geom
    _SIMPLIFY_CACHE[comune_key] = out
    return out


def load_index() -> ComuneIndex:
    data = json.loads(ISTAT_GEOJSON.read_text(encoding="utf-8"))
    idx = ComuneIndex()
    for primary, regions in ((True, REGIONS_PRIMARY), (False, REGIONS_BORDER)):
        for feat in data.get("features", []):
            props = feat.get("properties") or {}
            if props.get("reg_name") in regions and feat.get("geometry"):
                idx.add(props, feat["geometry"], primary)
    idx.finalize()
    print(f"[index] comuni indicizzati: {len(idx.keys)}")
    return idx


def _center(geom: dict) -> tuple[float, float]:
    pts: list[tuple[float, float]] = []

    def walk(c):
        if not c:
            return
        if isinstance(c[0], (int, float)):
            pts.append((c[0], c[1]))
        else:
            for x in c:
                walk(x)

    walk(geom.get("coordinates", []))
    if not pts:
        return 0.0, 0.0
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2


def _safe_text(path: Path) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            return pdf.pages[0].extract_text() or ""
    except Exception:
        return ""


# ----------------------------------------------------------------------------
# discovery per provider -> lista di record:
#   {comune_key, comune_name, zona, periodo, src: Path}
# ----------------------------------------------------------------------------
def discover_ags(idx: ComuneIndex) -> list[dict]:
    src = HERE / "ags_pdf"
    out: list[dict] = []
    for p in sorted(src.glob("*.pdf")):
        if p.stem.lower().startswith("rdp"):
            continue  # rapporti di prova grezzi: usiamo le schede per comune
        text = _safe_text(p)
        m = re.search(r"COMUNE DI\s+([^\n]+)", text, re.I)
        raw = m.group(1).strip() if m else re.sub(r"-\d+$", "", p.stem).replace("-", " ")
        hit = idx.match(raw)
        if not hit:
            print(f"[ags] no-match: {p.name} ({raw!r})")
            continue
        per = _period_from_text(text)
        out.append({"comune_key": _norm(hit["name"]), "comune": hit, "zona": hit["name"],
                    "periodo": per, "src": p})
    return out


def discover_mediochiampo(idx: ComuneIndex) -> list[dict]:
    src = HERE / "mediochiampo_pdf"
    out: list[dict] = []
    for p in sorted(src.glob("*.pdf")):
        text = _safe_text(p)
        m = re.search(r"Comune di\s+([A-Z][^\n]+)", text)
        raw = m.group(1).strip() if m else ""
        hit = idx.match(raw) if raw else None
        if not hit:
            print(f"[mediochiampo] no-match: {p.name} ({raw!r})")
            continue
        mz = re.search(r"\n([A-Z]{1,3}-\d+\s*-\s*[^\n]+)", text)
        zona = mz.group(1).strip() if mz else hit["name"]
        out.append({"comune_key": _norm(hit["name"]), "comune": hit, "zona": zona,
                    "periodo": _period_from_text(text), "src": p})
    return out


def discover_piaveservizi(idx: ComuneIndex) -> list[dict]:
    src = HERE / "piaveservizi_pdf"
    out: list[dict] = []
    for p in sorted(src.glob("*.pdf")):
        stem = p.stem.replace("_", " ")
        zona = stem
        m = re.search(r"in Comune\s+(?:di\s+)?(.+)$", stem, re.I)
        if not m:
            m = re.search(r"citt[a ]+di\s+(.+)$", stem, re.I)
        raw = (m.group(1) if m else re.sub(r"^Zona\s+", "", stem)).strip(" .")
        hits = _multi_match(idx, raw)
        if not hits:
            print(f"[piaveservizi] no-match: {p.name} ({raw!r})")
            continue
        per = _period_from_text(_safe_text(p))
        for hit in hits:
            out.append({"comune_key": _norm(hit["name"]), "comune": hit,
                        "zona": re.sub(r"^Zona\s+", "", zona), "periodo": per, "src": p})
    return out


def discover_gruppoveritas(idx: ComuneIndex) -> list[dict]:
    src = HERE / "gruppoveritas_pdf"
    out: list[dict] = []
    for p in sorted(src.glob("**/*.pdf")):
        m = re.match(r"^\d{4}_[a-z]+_-_\d{4}_[a-z]+_(.+?)_rev\d*", p.stem, re.I)
        raw = (m.group(1) if m else p.stem).replace("_", " ")
        hit = idx.match(raw)
        if not hit:
            print(f"[gruppoveritas] no-match: {p.name} ({raw!r})")
            continue
        per = _period_from_folder(p.parent.name) or _period_from_text(_safe_text(p))
        out.append({"comune_key": _norm(hit["name"]), "comune": hit,
                    "zona": _title(raw), "periodo": per, "src": p})
    return out


# AcegasApsAmga pubblica per zona di fornitura, non per comune. I comuni della
# Saccisica sono elencati nelle schede trimestrali storiche (la zona Padova e
# Trieste coincidono col comune capoluogo).
ACEGAS_ZONE_COMUNI = {
    "Padova": ["Padova"],
    "Trieste": ["Trieste"],
    "Saccisica": ["Piove di Sacco", "Brugine", "Legnaro", "Sant'Angelo di Piove di Sacco",
                  "Polverara", "Arzergrande", "Codevigo", "Correzzola", "Pontelongo",
                  "Cona", "Cavarzere"],
}

_ACEGAS_MONTHS = {m: i for i, m in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
     "agosto", "settembre", "ottobre", "novembre", "dicembre"], start=1)}


def _acegas_order(year: str, label: str) -> tuple[int, int]:
    low = (label or "").lower().strip()
    if low in _ACEGAS_MONTHS:
        m = _ACEGAS_MONTHS[low]
    else:
        mq = re.search(r"(\d)\D*trimestre", low)
        m = int(mq.group(1)) * 3 if mq else 0
    try:
        return int(year), m
    except (TypeError, ValueError):
        return 0, m


def discover_acegas(idx: ComuneIndex) -> list[dict]:
    """AcegasApsAmga (cartella dedicata): scheda piu' recente per zona, mappata
    ai comuni serviti (Padova, Trieste e gli 11 comuni della Saccisica)."""
    src = HERE / "acegasapsamga_qualita_acqua"
    csv_path = src / "pdfs.csv"
    if not csv_path.exists():
        return []
    by_zone: dict[str, list[dict]] = defaultdict(list)
    with io.open(csv_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "").lower() == "ok":
                by_zone[r.get("zone")].append(r)
    out: list[dict] = []
    for zone, comuni in ACEGAS_ZONE_COMUNI.items():
        rows = by_zone.get(zone) or []
        if not rows:
            continue
        rep = max(rows, key=lambda r: _acegas_order(r.get("year"), r.get("label")))
        p = HERE / (rep.get("pdf_file") or "").replace("\\", "/")
        if not p.exists():
            continue
        per = f"{rep.get('label')} {rep.get('year')}".strip()
        for cname in comuni:
            hit = idx.match(cname)
            if not hit:
                print(f"[acegasapsamga] no-match: {cname!r}")
                continue
            out.append({"comune_key": _norm(hit["name"]), "comune": hit,
                        "zona": zone, "periodo": per, "src": p})
    return out


def discover_etra(idx: ComuneIndex) -> list[dict]:
    src = HERE / "etra_pdf" / "analisi"
    out: list[dict] = []
    for p in sorted(src.glob("**/*.pdf")):
        text = _safe_text(p)
        raw = None
        m = re.search(r"Sito:\s*(.+)", text)
        if m:
            mm = re.search(r"([A-ZÀ-Ü][A-ZÀ-Ü'’ ]{2,})\s*$", m.group(1).strip())
            if mm:
                raw = mm.group(1)
        if not raw:
            m = re.search(r"prelievo:\s*[^,\n]+,\s*([^-\n]+?)\s*-", text)
            raw = m.group(1) if m else ""
        # Il comune e' in coda alla riga 'Sito:', ma l'indirizzo (tutto
        # maiuscolo) puo' precederlo: prova i suffissi di parole, dal piu' lungo.
        hit = None
        if raw:
            words = raw.split()
            for n in range(min(4, len(words)), 0, -1):
                hit = idx.match(" ".join(words[-n:]))
                if hit:
                    break
        if not hit:
            print(f"[etra] no-match: {p.name} ({raw!r})")
            continue
        mz = re.search(r"prelievo:\s*([^\n]+?)\s*-\s*pozzetto", text)
        zona = _clean_title(mz.group(1)) if mz else hit["name"]
        md = re.search(r"del\s*(\d{2})/(\d{2})/(\d{4})", text)
        per = f"{md.group(2)}/{md.group(3)}" if md else None
        out.append({"comune_key": _norm(hit["name"]), "comune": hit, "zona": zona,
                    "periodo": per, "src": p})
    return out


def discover_ats(idx: ComuneIndex) -> list[dict]:
    """Alto Trevigiano Servizi: i dati sono stati ricostruiti via API per
    coordinate (lat/lon), senza comune/via. Il comune si ricava per
    point-in-polygon dalle coordinate rappresentative in datasets.csv."""
    src = HERE / "ats_qualita_acqua"
    ds = src / "datasets.csv"
    if not ds.exists():
        return []
    out: list[dict] = []
    with io.open(ds, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "").lower() != "ok":
                continue
            pf = (r.get("pdf_file") or "").replace("\\", "/")
            p = HERE / pf
            if not p.exists():
                continue
            try:
                lat = float(r["representative_latitudine"])
                lon = float(r["representative_longitudine"])
            except (TypeError, ValueError):
                continue
            hit = idx.match_point(lat, lon)
            if not hit:
                print(f"[ats] fuori-poligono: {r.get('representative_label')!r} ({lat},{lon})")
                continue
            out.append({"comune_key": _norm(hit["name"]), "comune": hit,
                        "zona": hit["name"], "periodo": None, "src": p})
    return out


def discover_cafc(idx: ComuneIndex) -> list[dict]:
    """CAFC (Friuli Centrale): mapping_comune_indirizzo_pdf.csv associa ogni
    comune ai suoi PDF. Si tiene il PDF piu' ricorrente per comune."""
    src = HERE / "cafc_qualita_acqua"
    mp = src / "mapping_comune_indirizzo_pdf.csv"
    if not mp.exists():
        return []
    by_comune: dict[str, Counter] = defaultdict(Counter)
    with io.open(mp, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "").lower() != "ok":
                continue
            comune = (r.get("comune") or "").strip()
            pf = (r.get("pdf_file") or "").replace("\\", "/")
            if comune and pf:
                by_comune[comune][pf] += 1
    out: list[dict] = []
    for comune_raw, pdfs in by_comune.items():
        hit = idx.match(comune_raw)
        if not hit:
            print(f"[cafc] no-match: {comune_raw!r}")
            continue
        for pf, _ in pdfs.most_common():
            p = HERE / pf
            if p.exists():
                out.append({"comune_key": _norm(hit["name"]), "comune": hit,
                            "zona": hit["name"], "periodo": None, "src": p})
                break
    return out


def discover_lta_folder(idx: ComuneIndex) -> list[dict]:
    """LTA (Lemene, Veneto orientale / Pordenonese): cartella dedicata con
    mapping_comune_via_pdf.csv + datasets.csv (periodo). Un PDF rappresentativo
    per comune (il dataset che copre piu' vie). Sostituisce lo scrape inpage."""
    src = HERE / "lta_qualita_acqua"
    mp = src / "mapping_comune_via_pdf.csv"
    ds = src / "datasets.csv"
    if not mp.exists():
        return []
    ds_info: dict[str, dict] = {}
    if ds.exists():
        with io.open(ds, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                per = re.split(r"\s*\(pubblic", r.get("periodo") or "")[0].strip()
                ds_info[r["dataset_id"]] = {
                    "periodo": per or None,
                    "pdf": (r.get("pdf_file") or "").replace("\\", "/"),
                }
    by_comune: dict[str, Counter] = defaultdict(Counter)
    with io.open(mp, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "").lower() != "ok":
                continue
            comune = (r.get("comune") or "").strip()
            did = r.get("dataset_id")
            if comune and did:
                by_comune[comune][did] += 1
    out: list[dict] = []
    for comune_raw, counter in by_comune.items():
        hit = idx.match(comune_raw)
        if not hit:
            print(f"[lta] no-match: {comune_raw!r}")
            continue
        for did, _ in counter.most_common():
            info = ds_info.get(did)
            pf = info["pdf"] if info else f"lta_qualita_acqua/pdf/{did}.pdf"
            p = HERE / pf
            if p.exists():
                out.append({"comune_key": _norm(hit["name"]), "comune": hit,
                            "zona": hit["name"],
                            "periodo": info["periodo"] if info else None, "src": p})
                break
    return out


def _multi_match(idx: ComuneIndex, raw: str) -> list[dict]:
    """Prova match singolo; se fallisce, splitta sui separatori e infine fa una
    scansione a finestre di parole (per liste tipo 'Godega S.Urbano Orsago
    Cordignano' senza separatori espliciti)."""
    hit = idx.match(raw)
    if hit:
        return [hit]
    out, seen = [], set()
    for part in re.split(r"\s+-\s+|\s+e\s+|/|,", raw):
        h = idx.match(part.strip())
        if h and h["name"] not in seen:
            seen.add(h["name"])
            out.append(h)
    if out:
        return out
    words = [w for w in re.split(r"[\s.]+", raw) if len(w) >= 3 or w.lower() == "s"]
    for win in (3, 2, 1):
        for i in range(len(words) - win + 1):
            h = idx.match(" ".join(words[i:i + win]))
            if h and h["name"] not in seen:
                seen.add(h["name"])
                out.append(h)
    return out


# CSV-driven (inpage): site label -> provider id
# NB: LTA non e' piu' qui: ha una cartella dedicata (discover_lta_folder).
INPAGE_SITES = {
    "Acque Venete": "acquevenete",
    "Acque Veronesi": "acqueveronesi",
    "SIB": "sibspa",
    "Viacqua": "viacqua",
    "Acque del Chiampo": "acquedelchiampo",
}


def discover_inpage(idx: ComuneIndex) -> dict[str, list[dict]]:
    """Ritorna provider_id -> records, leggendo i CSV mapping/datasets."""
    ds_path = INPAGE_DIR / "all_datasets.csv"
    mp_path = INPAGE_DIR / "all_mapping.csv"
    datasets: dict[tuple[str, str], dict] = {}
    with io.open(ds_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            datasets[(r["site"], r["dataset_id"])] = r
    # (site, comune) -> Counter(dataset_id)
    by_sc: dict[tuple[str, str], Counter] = defaultdict(Counter)
    with io.open(mp_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = (r.get("comune") or "").strip()
            if c and r["site"] in INPAGE_SITES:
                by_sc[(r["site"], c)][r["dataset_id"]] += 1

    out: dict[str, list[dict]] = defaultdict(list)
    for (site, comune_raw), cnt in by_sc.items():
        prov = INPAGE_SITES[site]
        hit = idx.match(comune_raw)
        if not hit:
            print(f"[{prov}] no-match: {comune_raw!r}")
            continue
        # dataset rappresentativo = quello che copre piu' vie in quel comune
        for dataset_id, _ in cnt.most_common():
            row = datasets.get((site, dataset_id))
            if not row:
                continue
            pf = (row.get("pdf_file") or "").replace("\\", "/")
            src = HERE / pf
            if not src.exists():
                continue
            out[prov].append({
                "comune_key": _norm(hit["name"]), "comune": hit,
                "zona": _clean_title(row.get("title")) or hit["name"],
                "periodo": None, "src": src,
            })
            break
    return out


def _clean_title(t: str | None) -> str:
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    return t[:120]


# ----------------------------------------------------------------------------
# periodi
# ----------------------------------------------------------------------------
_MONTHS = ("gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
           "settembre|ottobre|novembre|dicembre")


def _period_from_text(text: str) -> str | None:
    if not text:
        return None
    low = text.lower()
    m = re.search(r"periodo di riferimento[:\s]*([^\n]+)", low)
    if m:
        return _shorten_period(m.group(1))
    m = re.search(r"\b([12]?\s*semestre[^\n]*?\d{4})", low)
    if m:
        return m.group(1).strip()
    m = re.search(rf"({_MONTHS})\s*\d{{4}}\s*-\s*({_MONTHS})\s*\d{{4}}", low)
    if m:
        return m.group(0)
    m = re.search(rf"(?:{_MONTHS})\s+\d{{4}}", low)
    if m:
        return m.group(0)
    m = re.search(r"\bsemestre\s+(\d{4})", low)
    if m:
        return m.group(0)
    return None


def _shorten_period(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" .;-")
    return s[:60]


def _period_from_folder(name: str) -> str | None:
    m = re.match(r"([a-z]+)(\d{4})_([a-z]+)(\d{4})", name.lower())
    if m:
        return f"{m.group(1)} {m.group(2)} - {m.group(3)} {m.group(4)}"
    return None


# ----------------------------------------------------------------------------
# provider metadata (per il GeoJSON; PROVIDER_META vive in external_sources.py)
# ----------------------------------------------------------------------------
PROVIDERS = {
    "ags": ("Azienda Gardesana Servizi", "ATO Veronese - Garda (VR)"),
    "mediochiampo": ("Medio Chiampo", "AATO Bacchiglione - Valle del Chiampo (VI)"),
    "piaveservizi": ("Piave Servizi", "ATO Veneto Orientale (TV)"),
    "gruppoveritas": ("Gruppo Veritas", "ATO Laguna di Venezia (VE)"),
    "acquevenete": ("Acque Venete", "ATO Polesine / Bacchiglione (RO/PD)"),
    "acqueveronesi": ("Acque Veronesi", "ATO Veronese (VR)"),
    "lta": ("LTA", "ATO Lemene (Veneto orientale / Pordenone)"),
    "sibspa": ("SIB", "ATO Alto Veneto (BL)"),
    "viacqua": ("Viacqua", "ATO Bacchiglione (VI)"),
    "acquedelchiampo": ("Acque del Chiampo", "AATO Valle del Chiampo (VI)"),
    "acegasapsamga": ("AcegasApsAmga", "ATO Bacchiglione / Trieste (gruppo Hera)"),
    "etra": ("Gruppo ETRA", "ATO Brenta — Alta Padovana e Bassano (PD/VI)"),
    "ats": ("Alto Trevigiano Servizi", "ATO Veneto Orientale — Trevigiano (TV/BL)"),
    "cafc": ("CAFC", "ATO Centrale Friuli (UD)"),
}


def build_provider(prov: str, records: list[dict]) -> int:
    label, ato = PROVIDERS[prov]
    # dedupe a UN record per comune (il primo / piu' rappresentativo)
    by_comune: dict[str, dict] = {}
    counts: Counter = Counter()
    for rec in records:
        counts[rec["comune_key"]] += 1
        by_comune.setdefault(rec["comune_key"], rec)

    for old in PDF_OUT_DIR.glob(f"{prov}_*.pdf"):
        old.unlink()

    features: list[dict] = []
    for ck, rec in sorted(by_comune.items()):
        com = rec["comune"]
        name = short_feature_name(prov, com["name"], f"{prov}|{ck}")
        shutil.copy2(rec["src"], PDF_OUT_DIR / f"{name}.pdf")
        geom = _simplify(ck, com["geometry"])
        lat, lon = _center(geom)
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "name": name,
                "comune": com["name"],
                "zona_label": rec["zona"],
                "regione": com["regione"],
                "provincia": com["provincia"],
                "provider": prov,
                "provider_label": label,
                "provider_ato": ato,
                "periodo": rec["periodo"],
                "n_zone": counts[ck],
                "lat": lat,
                "lon": lon,
                "source_pdf": rec["src"].name,
            },
        })

    out_file = DATA_DIR / f"mappa-qualita-{prov}.json"
    out_file.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
        "_built_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    print(f"[write] {out_file.name}: {len(features)} comuni "
          f"({len(records)} schede totali)")
    return len(features)


def main() -> int:
    if not ISTAT_GEOJSON.exists():
        print(f"[!] manca {ISTAT_GEOJSON}")
        return 1
    PDF_OUT_DIR.mkdir(parents=True, exist_ok=True)
    idx = load_index()

    records: dict[str, list[dict]] = {
        "ags": discover_ags(idx),
        "mediochiampo": discover_mediochiampo(idx),
        "piaveservizi": discover_piaveservizi(idx),
        "gruppoveritas": discover_gruppoveritas(idx),
        "acegasapsamga": discover_acegas(idx),
        "etra": discover_etra(idx),
        "ats": discover_ats(idx),
        "cafc": discover_cafc(idx),
        "lta": discover_lta_folder(idx),
    }
    records.update(discover_inpage(idx))

    total = 0
    for prov in PROVIDERS:
        total += build_provider(prov, records.get(prov, []))
    print(f"\n[veneto] TOTALE feature comunali: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
