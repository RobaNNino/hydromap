"""
HydroMap news engine.

Strategia:
  1.  Lancia in parallelo N "ricerche tematiche" su Gemini con grounding Google Search.
  2.  Da ogni risposta estrae sia il JSON strutturato (titolo, sommario, data, location, ...)
      SIA la lista dei `groundingChunks` (URI redirector Vertex AI, che *non vanno mai in 404*).
  3.  Per ogni news item, sceglie l'URL nel seguente ordine:
        - chunk di grounding mappato all'item (via posizione o match parole-chiave)
        - URL fornito da Gemini se passa un HEAD check
        - URL del primo chunk di grounding non ancora usato
        - None
  4.  Geocodifica `location` con Nominatim (cache disco).
  5.  Deduplica per titolo normalizzato, ordina per data desc.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Modello per le news. Default: gemini-2.5-flash — molto più economico di pro
# (ordine di grandezza ~10x sui token), e con grounding Google Search la
# qualità sulle news italiane resta accettabile. Override via env
# GEMINI_NEWS_MODEL se in futuro vuoi tornare a "gemini-2.5-pro".
GEMINI_MODEL = os.environ.get(
    "GEMINI_NEWS_MODEL",
    os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
)

# Finestra di freschezza: scarta notizie più vecchie di tot giorni.
NEWS_MAX_AGE_DAYS = int(os.environ.get("NEWS_MAX_AGE_DAYS", "30"))

DATA_DIR = Path(__file__).parent / "data"
GEOCACHE_FILE = DATA_DIR / "geocache.json"
NEWS_CACHE_FILE = DATA_DIR / "news_cache.json"


def load_news_cache() -> dict | None:
    """Legge la cache news persistita su disco (sopravvive ai cold-start)."""
    if not NEWS_CACHE_FILE.exists():
        return None
    try:
        d = json.loads(NEWS_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("items"), list):
            return d
    except Exception:
        return None
    return None


def save_news_cache(data: dict) -> None:
    """Persiste la cache news su disco in modo atomico."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = NEWS_CACHE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(NEWS_CACHE_FILE)
    except Exception:
        pass

# Topic = (label, prompt extension, default category, default severity)
# Priorità ASSOLUTA a Roma e provincia. I topic "nazionali" servono solo
# come complemento ma vengono pesati meno nell'ordinamento finale.
TOPICS = [
    # ====== TOPIC DEDICATI ROMA (peso maggiore) ======
    ("roma_acea_avvisi",
     "avvisi ufficiali Acea Ato 2 e Acea ATO2 SpA per Roma e provincia: "
     "sospensioni idriche, interruzioni acqua, chiusure forniture, "
     "abbassamenti di pressione, lavori in corso nei municipi di Roma "
     "(I, II, III, IV, V, VI, VII, VIII, IX, X, XI, XII, XIII, XIV, XV) "
     "e comuni serviti (Fiumicino, Ciampino, Pomezia, Anzio, Nettuno, "
     "Frascati, Marino, Albano, Velletri, Bracciano, Cerveteri, Ladispoli, "
     "Tivoli, Guidonia, Mentana, Monterotondo). Cerca anche su "
     "acea.it/ato2 e siti dei comuni",
     "infrastruttura", "warning"),
    ("roma_guasti",
     "guasti idrici, rotture condotte, allagamenti da tubature, perdite "
     "rete acqua a Roma città e quartieri (Trastevere, Testaccio, Garbatella, "
     "Ostiense, San Lorenzo, Pigneto, Prati, Parioli, Trieste, Salario, "
     "Nomentano, Tiburtino, San Giovanni, Appio, Tuscolano, Eur, Ostia, "
     "Aurelio, Monteverde, Boccea, Cassia, Flaminio, Trionfale, Casilino, "
     "Centocelle, Quadraro, Magliana, Portuense)",
     "infrastruttura", "alert"),
    ("roma_qualita",
     "qualità acqua potabile a Roma e Lazio: analisi, controlli ASL Roma, "
     "ARPA Lazio, ISS, presenza di arsenico, fluoro, vanadio, nitrati, "
     "PFAS, cloriti, trialometani nei rubinetti romani; report Acea sui "
     "parametri delle 14 zone di approvvigionamento di Roma",
     "controllo", "info"),
    ("roma_ordinanze",
     "ordinanze sindacali del Comune di Roma Capitale o comuni della "
     "Città Metropolitana di Roma: divieto uso acqua potabile, non potabilità, "
     "uso limitato, revoche; anche ordinanze ASL Roma 1/2/3/4/5/6",
     "ordinanza", "warning"),
    ("roma_lavori_pnrr",
     "lavori PNRR, cantieri rete idrica e fognaria a Roma, nuovo "
     "raddoppio Peschiera-Capore, ammodernamenti acquedotti romani "
     "(Marcio, Vergine, Felice, Paolo, Peschiera, Appio Alessandrino), "
     "interventi su collettori e depuratori (Roma Sud, Roma Nord, "
     "Roma Est, Ostia, Fregene)",
     "infrastruttura", "info"),
    ("roma_nasoni_fontane",
     "nasoni di Roma (fontanelle pubbliche), Acea, manutenzione, "
     "chiusure estive, fontane storiche (Trevi, Quattro Fiumi, Tritone) "
     "e qualità dell'acqua nei nasoni",
     "infrastruttura", "info"),
    # ====== TOPIC LAZIO + NAZIONALI (peso minore) ======
    ("lazio_contaminazione",
     "contaminazioni acqua potabile nel Lazio fuori Roma: arsenico nei "
     "Castelli Romani e Viterbese, PFAS, batteri, metalli pesanti; "
     "provincia di Viterbo, Frosinone, Latina, Rieti",
     "contaminazione", "alert"),
    ("italia_contaminazione",
     "contaminazioni dell'acqua potabile (PFAS, batteri, arsenico, "
     "nitrati, escherichia coli, legionella) in Italia",
     "contaminazione", "alert"),
    ("italia_normativa",
     "novità normative italiane ed europee su acqua potabile, "
     "direttiva DWD 2020/2184, valori limite PFAS, microplastiche",
     "normativa", "info"),
]

# Comuni serviti da Acea Ato 2 / Città Metropolitana di Roma (per ranking)
ROMA_AREA_TOKENS = {
    "roma", "fiumicino", "ciampino", "pomezia", "anzio", "nettuno",
    "frascati", "marino", "albano", "velletri", "bracciano", "cerveteri",
    "ladispoli", "tivoli", "guidonia", "mentana", "monterotondo",
    "grottaferrata", "rocca di papa", "genzano", "ariccia", "lanuvio",
    "castel gandolfo", "anguillara", "trevignano", "manziana", "santa marinella",
    "civitavecchia", "colleferro", "valmontone", "palestrina", "zagarolo",
    "ostia", "fregene", "acilia", "fiumicino", "città metropolitana di roma",
    "lazio", "acea", "acea ato 2", "ato 2",
}

CATEGORY_META = {
    "contaminazione": {"icon": "☣️", "color": "#dc2626"},
    "ordinanza":     {"icon": "🛑", "color": "#ea580c"},
    "infrastruttura": {"icon": "🔧", "color": "#0284c7"},
    "siccità":       {"icon": "🌵", "color": "#ca8a04"},
    "controllo":     {"icon": "🔬", "color": "#0d9488"},
    "normativa":     {"icon": "📜", "color": "#7c3aed"},
    "altro":         {"icon": "💧", "color": "#475569"},
}

# Geocache (disk-persistent) + lock
_geo_lock = threading.Lock()

# Lista (thread-safe in CPython per le list ops) degli errori dell'ultima fetch
# usata per fornire un messaggio chiaro al frontend.
_LAST_ERRORS: list[str] = []


def _build_error_summary(items: list) -> str | None:
    """Se non abbiamo news e tutti i topic hanno fallito, ritorna un messaggio
    user-friendly che riassume il motivo (quota Gemini, rete, ecc.)."""
    if items:
        return None
    if not _LAST_ERRORS:
        return None
    if any(e == "quota_exhausted" for e in _LAST_ERRORS):
        return (
            "Quota Gemini esaurita: il progetto Google AI Studio ha superato "
            "il monthly spending cap. Aumenta o rimuovi il limite su "
            "https://aistudio.google.com/usage e riprova."
        )
    if any(e.startswith("http ") for e in _LAST_ERRORS):
        return f"Errore API Gemini ({_LAST_ERRORS[0]}). Riprova tra qualche minuto."
    if any(e.startswith("network") for e in _LAST_ERRORS):
        return "Errore di rete verso l'API Gemini. Controlla la connessione."
    return "Errore sconosciuto durante il recupero notizie."


if GEOCACHE_FILE.exists():
    try:
        _geocache: dict = json.loads(GEOCACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        _geocache = {}
else:
    _geocache = {}


def _save_geocache() -> None:
    try:
        GEOCACHE_FILE.write_text(json.dumps(_geocache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def geocode(location: str) -> tuple[float, float] | None:
    if not location:
        return None
    key = _normalize(location)
    if not key:
        return None
    with _geo_lock:
        if key in _geocache:
            v = _geocache[key]
            return (v[0], v[1]) if v else None
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location + ", Italia", "format": "json", "limit": 1,
                    "countrycodes": "it"},
            headers={"User-Agent": "HydroMap/1.0 (educational)"},
            timeout=8,
        )
        if r.status_code == 200:
            arr = r.json()
            if arr:
                lat = float(arr[0]["lat"])
                lon = float(arr[0]["lon"])
                with _geo_lock:
                    _geocache[key] = [lat, lon]
                    _save_geocache()
                return (lat, lon)
        with _geo_lock:
            _geocache[key] = None
            _save_geocache()
    except Exception:
        pass
    return None


def _gemini_call(topic_key: str, topic_desc: str, default_cat: str,
                 default_sev: str, n_items: int = 6) -> tuple[list[dict], list[dict]]:
    """Returns (items, grounding_chunks)."""
    today = datetime.utcnow().date()
    min_date = today - timedelta(days=NEWS_MAX_AGE_DAYS)
    prompt = (
        f"Sei un giornalista specializzato in cronaca idrica italiana. "
        f"Oggi è il {today.isoformat()}. "
        f"Usa Google Search per trovare le {n_items} notizie italiane PIÙ "
        f"RECENTI (data >= {min_date.isoformat()}) su: {topic_desc}.\n\n"
        f"Per ciascuna notizia DEVI fornire:\n"
        f"- una data REALE in formato YYYY-MM-DD (non inventarla, leggila dall'articolo);\n"
        f"- una LOCATION specifica: comune o quartiere italiano citato, "
        f"quanto più preciso possibile (es. 'Bracciano (RM)', 'Roma Trastevere', "
        f"'Frosinone'); se la notizia è nazionale scrivi 'Italia';\n"
        f"- un URL della fonte originale.\n\n"
        f"Includi anche manutenzioni o interruzioni FUTURE già annunciate.\n"
        f"Rispondi ESCLUSIVAMENTE con JSON valido senza markdown:\n"
        f'{{"items":[{{'
        f'"title":"titolo",'
        f'"summary":"riassunto in 2-3 frasi concrete con numeri, date e luogo specifico",'
        f'"source":"nome testata",'
        f'"url":"URL pagina notizia",'
        f'"date":"YYYY-MM-DD",'
        f'"location":"Comune/Provincia italiana citata, oppure Italia",'
        f'"category":"contaminazione|ordinanza|infrastruttura|siccità|controllo|normativa",'
        f'"severity":"info|warning|alert",'
        f'"is_future":false,'
        f'"keywords":["3-5 parole chiave"]'
        f"}}]}}\n"
        f"Imposta is_future=true se la notizia si riferisce a un evento "
        f"programmato per i prossimi giorni (manutenzione, sospensione, lavori)."
    )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
    }
    # Modelli da provare in ordine: configurato → fallback flash (se diverso)
    models_chain = [GEMINI_MODEL]
    if GEMINI_MODEL != "gemini-2.5-flash":
        models_chain.append("gemini-2.5-flash")
    resp = None
    last_error: str | None = None
    for model_name in models_chain:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={GEMINI_API_KEY}"
        )
        for attempt in range(3):
            try:
                resp = requests.post(url, json=body, timeout=70)
            except requests.RequestException as e:
                last_error = f"network: {e}"
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 200:
                break
            # Errori persistenti (quota/budget esaurito): inutile riprovare
            body_txt = resp.text or ""
            if resp.status_code == 429 and ("spending cap" in body_txt.lower() or "RESOURCE_EXHAUSTED" in body_txt):
                last_error = "quota_exhausted"
                break
            if resp.status_code in (429, 503):
                last_error = f"http {resp.status_code}"
                time.sleep(2 ** attempt + 1)
                continue
            last_error = f"http {resp.status_code}"
            break
        if resp is not None and resp.status_code == 200:
            last_error = None
            break  # success on this model
    if resp is None or resp.status_code != 200:
        # Esporta l'errore a livello di modulo per l'endpoint
        if last_error:
            _LAST_ERRORS.append(last_error)
        return [], []
    try:
        payload = resp.json()
        cand = payload["candidates"][0]
        raw = cand["content"]["parts"][0]["text"] or ""
        chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
    except (KeyError, IndexError, ValueError):
        return [], []

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    s, e = raw.find("{"), raw.rfind("}")
    items: list[dict] = []
    if s != -1 and e != -1:
        try:
            items = (json.loads(raw[s:e + 1]) or {}).get("items") or []
        except json.JSONDecodeError:
            items = []
    # Inject topic defaults if missing
    for it in items:
        it.setdefault("category", default_cat)
        it.setdefault("severity", default_sev)
        it["_topic"] = topic_key
    # Normalize grounding chunks shape: {web:{uri, title}}
    norm_chunks = []
    for c in chunks:
        w = c.get("web") or {}
        if w.get("uri"):
            norm_chunks.append({"uri": w["uri"], "title": w.get("title", "")})
    return items, norm_chunks


def _url_ok(u: str) -> bool:
    if not u or not u.startswith("http"):
        return False
    try:
        r = requests.head(u, allow_redirects=True, timeout=5,
                          headers={"User-Agent": "Mozilla/5.0 HydroMap"})
        if 200 <= r.status_code < 400:
            return True
        # alcuni siti bloccano HEAD, ritento con GET range
        if r.status_code in (403, 405, 501):
            r2 = requests.get(u, allow_redirects=True, timeout=6, stream=True,
                              headers={"User-Agent": "Mozilla/5.0 HydroMap",
                                       "Range": "bytes=0-128"})
            return 200 <= r2.status_code < 400
        return False
    except requests.RequestException:
        return False


def _pick_url(item: dict, item_idx: int, chunks: list[dict],
              used: set[str]) -> tuple[str | None, str | None]:
    """Sceglie l'URL migliore e ritorna anche il "publisher" (host pulito)."""
    candidates: list[str] = []

    # 1) chunk allineato per posizione
    if item_idx < len(chunks):
        candidates.append(chunks[item_idx]["uri"])
    # 2) chunk con titolo che matcha parole chiave del titolo dell'item
    title_norm = _normalize(item.get("title") or "")
    title_tokens = set(t for t in title_norm.split() if len(t) > 4)
    if title_tokens:
        for c in chunks:
            ct = _normalize(c.get("title") or "")
            if title_tokens & set(ct.split()):
                candidates.append(c["uri"])
    # 3) URL Gemini se non sembra ovviamente fasullo
    g_url = (item.get("url") or "").strip()
    if g_url.startswith("http"):
        candidates.append(g_url)
    # 4) primo chunk non usato
    for c in chunks:
        candidates.append(c["uri"])

    # dedup preservando ordine
    seen = set()
    ordered: list[str] = []
    for u in candidates:
        if u and u not in seen:
            seen.add(u)
            ordered.append(u)

    for u in ordered:
        if u in used:
            continue
        if u.startswith("https://vertexaisearch.cloud.google.com/"):
            # Redirector Google = praticamente sempre valido
            used.add(u)
            return u, _host_of(u)
        if _url_ok(u):
            used.add(u)
            return u, _host_of(u)
    return (ordered[0] if ordered else None), (
        _host_of(ordered[0]) if ordered else None
    )


_HOST_RX = re.compile(r"https?://([^/]+)")


def _host_of(u: str) -> str | None:
    if not u:
        return None
    m = _HOST_RX.match(u)
    if not m:
        return None
    h = m.group(1).lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def fetch_news(limit_per_topic: int = 6, max_workers: int = 8) -> dict:
    if not GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY not set", "items": []}

    _LAST_ERRORS.clear()
    all_items: list[dict] = []
    all_chunks: list[dict] = []
    # 1) ricerche parallele tematiche
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(_gemini_call, t[0], t[1], t[2], t[3], limit_per_topic): t[0]
            for t in TOPICS
        }
        per_topic_chunks: dict[str, list[dict]] = {}
        per_topic_items: dict[str, list[dict]] = {}
        for f in as_completed(futs):
            tkey = futs[f]
            try:
                items, chunks = f.result()
            except Exception:
                items, chunks = [], []
            per_topic_items[tkey] = items
            per_topic_chunks[tkey] = chunks
            all_chunks.extend(chunks)

    # 2) per ogni topic, risolvi URL contestualmente al suo set di chunks
    used_urls: set[str] = set()
    for tkey, items in per_topic_items.items():
        chunks = per_topic_chunks.get(tkey, [])
        for i, it in enumerate(items):
            u, host = _pick_url(it, i, chunks, used_urls)
            it["url"] = u
            it["source"] = it.get("source") or host or ""
            all_items.append(it)

    # 3) dedup per titolo normalizzato
    seen_titles: set[str] = set()
    dedup: list[dict] = []
    for it in all_items:
        key = _normalize(it.get("title") or "")[:80]
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        dedup.append(it)

    # 3.bis) filtro freschezza (scarta notizie più vecchie di NEWS_MAX_AGE_DAYS,
    # tranne quelle marcate come 'future' che possono avere data odierna o futura)
    today = datetime.utcnow().date()
    min_date = today - timedelta(days=NEWS_MAX_AGE_DAYS)
    fresh: list[dict] = []
    for it in dedup:
        d_str = (it.get("date") or "").strip()
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", d_str)
        if not m:
            # senza data verificabile: la teniamo solo per topic 'manutenzioni/lavori' (futuri)
            if it.get("_topic") in ("manutenzioni_programmate", "lavori_cantieri"):
                fresh.append(it)
            continue
        try:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            continue
        if d < min_date:
            continue
        if d > today + timedelta(days=180):
            # date troppo lontane: probabilmente errore
            continue
        it["is_future"] = bool(it.get("is_future")) or d > today
        fresh.append(it)
    dedup = fresh

    # 4) geocode in parallelo con fallback: ogni item DEVE finire sulla mappa
    locs = [it.get("location") for it in dedup]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(geocode, locs))
    for it, ll in zip(dedup, results):
        if ll:
            it["lat"], it["lng"] = ll
            it["geo_quality"] = "exact"
        else:
            # tenta di geocodificare i primi keyword (es. nome ente o testata)
            kw_loc = None
            for kw in (it.get("keywords") or [])[:3]:
                if kw and any(c.isalpha() for c in kw):
                    kw_loc = geocode(kw)
                    if kw_loc:
                        break
            if kw_loc:
                it["lat"], it["lng"] = kw_loc
                it["geo_quality"] = "approx"
            else:
                # fallback: cluster sopra Roma con jitter deterministico
                seed = int(hashlib.md5((it.get("title") or "").encode()).hexdigest()[:8], 16)
                rnd = random.Random(seed)
                # raggio ~25 km attorno al Campidoglio
                it["lat"] = 41.8933 + rnd.uniform(-0.18, 0.18)
                it["lng"] = 12.4830 + rnd.uniform(-0.22, 0.22)
                it["geo_quality"] = "fallback"
    # 5) ordina per (priorità Roma, data desc)
    def _roma_score(it: dict) -> int:
        """2 = Roma città/municipi, 1 = provincia/Lazio/Acea, 0 = altrove."""
        hay = " ".join([
            str(it.get("location") or ""),
            str(it.get("title") or ""),
            str(it.get("summary") or ""),
            " ".join(it.get("keywords") or []),
        ]).lower()
        if "roma" in hay or "capitolin" in hay or "capitale" in hay:
            return 2
        for tok in ROMA_AREA_TOKENS:
            if tok in hay:
                return 1
        return 0

    def _date_key(it: dict) -> str:
        d = (it.get("date") or "").strip()
        return d if re.match(r"\d{4}-\d{2}-\d{2}", d) else "0000-00-00"

    # Score combinato: prima Roma, poi data più recente
    dedup.sort(key=lambda it: (_roma_score(it), _date_key(it)), reverse=True)

    # Marca le notizie Roma per evidenza in UI
    for it in dedup:
        s = _roma_score(it)
        it["is_rome"] = s == 2
        it["is_lazio"] = s >= 1

    # 6) metadata categoria
    for it in dedup:
        cat = (it.get("category") or "altro").lower().strip()
        if cat not in CATEGORY_META:
            cat = "altro"
        it["category"] = cat
        it["icon"] = CATEGORY_META[cat]["icon"]
        it["color"] = CATEGORY_META[cat]["color"]

    return {
        "items": dedup,
        "categories": CATEGORY_META,
        "model": GEMINI_MODEL,
        "generated_at": int(time.time()),
        "total_chunks": len(all_chunks),
        "error": _build_error_summary(dedup),
    }
