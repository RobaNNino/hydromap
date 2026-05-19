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

import json
import os
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
# Default ridotto a 14gg per avere solo cose realmente attuali.
NEWS_MAX_AGE_DAYS = int(os.environ.get("NEWS_MAX_AGE_DAYS", "14"))

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

# Topic = (label, prompt extension, default category, default severity).
#
# Strategia v2 (mag 2026): meno news ma diffuse su TUTTE le province del Lazio.
# Solo cose IMPORTANTI (guasti/contaminazioni/ordinanze) + manutenzioni
# programmate. Niente filler informativo (qualità routine, news nazionali
# generiche) e niente notizie passate (filtrate sotto a 14gg).
TOPICS = [
    ("prov_roma_eventi",
     "guasti idrici, interruzioni, sospensioni e ordinanze su acqua "
     "potabile nella Città Metropolitana di Roma (Acea Ato 2): Roma "
     "città, Fiumicino, Ciampino, Pomezia, Tivoli, Guidonia, Frascati, "
     "Bracciano, Cerveteri, Ladispoli, Albano. Solo eventi reali con "
     "data certa e comune ben identificato",
     "infrastruttura", "warning"),
    ("prov_frosinone",
     "guasti, contaminazioni, ordinanze di non potabilità o sospensioni "
     "acqua potabile in provincia di Frosinone (Acea Ato 5): Frosinone, "
     "Cassino, Sora, Anagni, Ferentino, Alatri, Veroli, Ceccano, Pontecorvo. "
     "Indica sempre il comune preciso",
     "infrastruttura", "warning"),
    ("prov_latina",
     "guasti, contaminazioni, ordinanze e sospensioni acqua potabile in "
     "provincia di Latina (Acqualatina): Latina, Aprilia, Terracina, "
     "Fondi, Formia, Gaeta, Sabaudia, Cisterna, Sezze, Priverno, Itri, "
     "Sperlonga. Indica sempre il comune preciso",
     "infrastruttura", "warning"),
    ("prov_viterbo",
     "guasti, contaminazioni (arsenico, fluoro), ordinanze e sospensioni "
     "acqua potabile in provincia di Viterbo (Talete SpA): Viterbo, "
     "Civita Castellana, Tarquinia, Montefiascone, Vetralla, Tuscania, "
     "Bagnoregio, Soriano nel Cimino. Indica sempre il comune preciso",
     "contaminazione", "alert"),
    ("prov_rieti",
     "guasti, ordinanze, sospensioni acqua potabile in provincia di Rieti "
     "(APS – Acqua Pubblica Sabina): Rieti, Cittaducale, Poggio Mirteto, "
     "Magliano Sabina, Fara in Sabina, Montopoli, Borgorose, Antrodoco. "
     "Indica sempre il comune preciso",
     "infrastruttura", "warning"),
    ("manutenzioni_programmate",
     "manutenzioni programmate, interventi annunciati, sospensioni "
     "idriche pianificate per i PROSSIMI 14 giorni dai gestori Acea "
     "Ato 2, Acea Ato 5, Acqualatina, Talete, Acqua Pubblica Sabina. "
     "Solo eventi futuri con data e comune specifico",
     "infrastruttura", "info"),
    ("lazio_contaminazioni_gravi",
     "contaminazioni gravi acqua potabile nel Lazio: PFAS, arsenico oltre "
     "limite, escherichia coli, legionella, ordinanze ASL di non "
     "potabilità. Specifica comune e provincia",
     "contaminazione", "alert"),
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


# Termini troppo generici da rigettare: non possiamo piazzare un pin preciso
_GENERIC_LOC_TOKENS = {
    "italia", "lazio", "provincia", "regione", "nazionale", "sud",
    "nord", "centro", "penisola", "ato", "",
}


def geocode_item(it: dict) -> tuple[float, float, str] | None:
    """Geocodifica precisa per un item news.

    Ordine dei tentativi:
      1) 'Comune, Provincia, Italia' (massima precisione)
      2) location grezza se contiene una virgola (es. 'Bracciano (RM)')
    Se nessuno dei due funziona ritorna None: l'item verrà scartato.
    """
    comune = (it.get("comune") or "").strip()
    provincia = (it.get("provincia") or "").strip()
    location = (it.get("location") or "").strip()

    # rifiuta location generiche tipo 'Italia' / 'Lazio'
    nrm = _normalize(location)
    if nrm in _GENERIC_LOC_TOKENS:
        comune = comune or ""
    if comune and provincia:
        ll = geocode(f"{comune}, {provincia}")
        if ll:
            return (ll[0], ll[1], f"{comune}, {provincia}")
    if comune:
        ll = geocode(comune)
        if ll:
            return (ll[0], ll[1], comune)
    if location and _normalize(location) not in _GENERIC_LOC_TOKENS:
        ll = geocode(location)
        if ll:
            return (ll[0], ll[1], location)
    return None


def _gemini_call(topic_key: str, topic_desc: str, default_cat: str,
                 default_sev: str, n_items: int = 4) -> tuple[list[dict], list[dict]]:
    """Returns (items, grounding_chunks)."""
    today = datetime.utcnow().date()
    min_date = today - timedelta(days=NEWS_MAX_AGE_DAYS)
    prompt = (
        f"Sei un giornalista specializzato in cronaca idrica italiana. "
        f"Oggi è il {today.isoformat()}. "
        f"Usa Google Search per trovare al massimo {n_items} notizie REALI "
        f"e VERIFICABILI su: {topic_desc}.\n\n"
        f"REGOLE FERREE (se non riesci a rispettarle, NON includere la notizia):\n"
        f"1. Data dell'articolo >= {min_date.isoformat()} (max 14 giorni fa), "
        f"   oppure data di un evento programmato per i prossimi 21 giorni.\n"
        f"2. Severity SOLO 'warning' o 'alert' (cose importanti: guasti, "
        f"   contaminazioni, ordinanze, sospensioni). Usa 'info' SOLO per "
        f"   manutenzioni programmate future con data certa.\n"
        f"3. Location DEVE essere 'Comune, Provincia' italiano specifico "
        f"   (es. 'Bracciano, Roma' / 'Civita Castellana, Viterbo'). "
        f"   NON usare 'Italia', 'Lazio', 'provincia di X' generici: scarta "
        f"   la notizia se non c'è un comune preciso.\n"
        f"4. La notizia deve avere impatto idrico CONCRETO (utenti senza "
        f"   acqua, parametro fuori limite, divieto di consumo, lavori in "
        f"   corso). Niente cronaca generica, niente comunicati istituzionali "
        f"   vuoti, niente articoli di opinione.\n\n"
        f"Rispondi ESCLUSIVAMENTE con JSON valido senza markdown:\n"
        f'{{"items":[{{'
        f'"title":"titolo conciso",'
        f'"summary":"riassunto in 2 frasi con numeri, comune e impatto",'
        f'"source":"nome testata",'
        f'"url":"URL pagina notizia",'
        f'"date":"YYYY-MM-DD",'
        f'"comune":"nome del comune",'
        f'"provincia":"sigla provincia (RM/FR/LT/VT/RI)",'
        f'"location":"Comune, Provincia",'
        f'"category":"contaminazione|ordinanza|infrastruttura|siccità|controllo|normativa",'
        f'"severity":"warning|alert|info",'
        f'"is_future":false,'
        f'"keywords":["3-5 parole chiave"]'
        f"}}]}}\n"
        f"Se non trovi nulla che rispetti le regole, restituisci items:[]."
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


def fetch_news(limit_per_topic: int = 4, max_workers: int = 8) -> dict:
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

    # 4) geocode preciso (comune+provincia). Gli item che non
    #    geocodificano in modo affidabile vengono SCARTATI: niente più
    #    jitter casuale sopra Roma, ogni pin deve essere reale.
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(geocode_item, dedup))
    geo_ok: list[dict] = []
    for it, res in zip(dedup, results):
        if not res:
            continue
        it["lat"], it["lng"], it["location"] = res
        it["geo_quality"] = "exact"
        geo_ok.append(it)
    dedup = geo_ok

    # 4.bis) filtro importanza: solo warning/alert + manutenzioni programmate
    important: list[dict] = []
    for it in dedup:
        sev = (it.get("severity") or "").lower()
        if sev in ("alert", "warning"):
            important.append(it)
        elif it.get("is_future") and (it.get("category") or "") == "infrastruttura":
            important.append(it)
    dedup = important
    # 5) ordina per data desc (la zonizzazione è garantita dai topic)
    def _date_key(it: dict) -> str:
        d = (it.get("date") or "").strip()
        return d if re.match(r"\d{4}-\d{2}-\d{2}", d) else "0000-00-00"

    dedup.sort(key=_date_key, reverse=True)

    # Marca le notizie Roma solo per il badge in UI (non per il ranking)
    for it in dedup:
        hay = " ".join([
            str(it.get("location") or ""),
            str(it.get("provincia") or ""),
            str(it.get("comune") or ""),
        ]).lower()
        prov = (it.get("provincia") or "").lower()
        it["is_rome"] = (prov == "rm") or ("roma" in hay)
        it["is_lazio"] = it["is_rome"] or any(
            p in hay or prov == p for p in ("fr", "lt", "vt", "ri")
        ) or any(tok in hay for tok in ROMA_AREA_TOKENS)

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
