"""
AcquaMap backend.
Endpoints:
  GET  /                            -> serve frontend
  GET  /api/geojson                 -> map polygons with status+links
  GET  /api/zone/<name>             -> parsed PDF result + PDF passthrough URL
  GET  /api/pdf/<name>              -> stream PDF
  GET  /api/news?limit=5            -> latest Italian water news via Gemini grounding
"""
from __future__ import annotations

import gc
import gzip
import json
import os
import sys
import threading
import time
from datetime import date
from pathlib import Path

# Permette gli import "flat" (from news_engine import ...) sia quando lanciamo
# `python backend/app.py` localmente, sia quando gunicorn lancia `backend.app:app`
# dalla root del progetto (in quel caso senza questa riga `news_engine` non si trova).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ROOT = Path(__file__).parent / "data"
PDF_DIR = ROOT / "pdfs"
# Mappa provider_id -> file GeoJSON locale (popolato da scrape.py / scraper dedicati).
# I file vengono uniti in un singolo FeatureCollection alla prima richiesta.
GEOJSON_FILES: dict[str, Path] = {
    "acea_ato2": ROOT / "mappa-qualita-ato-2.json",
    "acea_ato5": ROOT / "mappa-qualita-ato-5.json",
    "acqualatina": ROOT / "mappa-qualita-acqualatina.json",
    "acqua_pubblica_sabina": ROOT / "mappa-qualita-aps.json",
    "abruzzo": ROOT / "mappa-qualita-abruzzo.json",
    "campania": ROOT / "mappa-qualita-campania.json",
    "molise": ROOT / "mappa-qualita-molise.json",
    "puglia": ROOT / "mappa-qualita-puglia.json",
    "basilicata": ROOT / "mappa-qualita-basilicata.json",
    "toscana_nuoveacque": ROOT / "mappa-qualita-nuoveacque.json",
    "lazio_extra": ROOT / "mappa-qualita-lazio-extra.json",
}
RESULTS_FILE = ROOT / "results.json"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

app = Flask(__name__, static_folder=None)
# CORS configurabile via env (es. "https://hydromap.netlify.app,https://acqua-roma.it").
# Default "*" per sviluppo locale.
_cors_origins = os.environ.get("CORS_ORIGINS", "*")
if _cors_origins == "*":
    CORS(app)
else:
    CORS(app, resources={r"/api/*": {"origins": [o.strip() for o in _cors_origins.split(",")]}})


# ---------- data loading ----------
def _load_results() -> dict:
    if RESULTS_FILE.exists():
        try:
            return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


_RESULTS = _load_results()
_GEOJSON_CACHE: dict | None = None
# Cache della risposta serializzata (e gzippata) per /api/geojson.
# Rebuild solo quando cambia la data (freshness dipende da date.today()).
_GEOJSON_RESP_CACHE: dict = {
    "date": None,        # date.today() del build
    "json_bytes": None,  # bytes UTF-8 JSON
    "gz_bytes": None,    # bytes gzippati
}
_GEOJSON_RESP_LOCK = threading.Lock()


# ---------- freshness analisi (data analisi → "nuova"/"in scadenza"/"vecchia") ----------
_MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
# Soglie configurabili (in mesi) — il D.Lgs 18/2023 raccomanda controlli almeno annuali
# per i parametri di routine, quindi >12 mesi = analisi obsoleta.
FRESH_MAX_MONTHS = int(os.environ.get("FRESH_MAX_MONTHS", "6"))      # <=6 mesi = "nuova"
FRESH_WARN_MONTHS = int(os.environ.get("FRESH_WARN_MONTHS", "12"))   # 7-12 = "in scadenza", >12 = "vecchia"


def _parse_periodo(periodo: str | None) -> tuple[int, int] | None:
    """Estrae (anno, mese) da una stringa tipo 'settembre 2024', '09/2024',
    '2024-09', 'Secondo Semestre 2025', 'I Trimestre 2025', 'II semestre 2025'."""
    if not periodo:
        return None
    s = str(periodo).strip().lower()
    # 'settembre 2024'
    import re as _re
    m = _re.search(r"\b(" + "|".join(_MONTHS_IT.keys()) + r")\b[^\d]*(\d{4})", s)
    if m:
        return int(m.group(2)), _MONTHS_IT[m.group(1)]
    # 'primo/secondo/terzo/quarto trimestre 2025' o 'I/II/III/IV trimestre'
    m = _re.search(r"\b(primo|secondo|terzo|quarto|i{1,3}v?|iv)\s*trimestre[^\d]*(\d{4})", s)
    if m:
        q = {"primo": 1, "i": 1, "secondo": 2, "ii": 2, "terzo": 3, "iii": 3,
             "quarto": 4, "iv": 4}.get(m.group(1), 1)
        month = q * 3  # fine trimestre
        return int(m.group(2)), month
    # 'primo/secondo semestre 2025' o 'I/II semestre'
    m = _re.search(r"\b(primo|secondo|i{1,2})\s*semestre[^\d]*(\d{4})", s)
    if m:
        h = {"primo": 1, "i": 1, "secondo": 2, "ii": 2}.get(m.group(1), 1)
        month = 6 if h == 1 else 12  # fine semestre
        return int(m.group(2)), month
    # '09/2024' or '9-2024'
    m = _re.search(r"\b(0?[1-9]|1[0-2])[\/\-\.](\d{4})\b", s)
    if m:
        return int(m.group(2)), int(m.group(1))
    # '2024-09'
    m = _re.search(r"\b(\d{4})[\/\-\.](0?[1-9]|1[0-2])\b", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    # solo anno
    m = _re.search(r"\b(20\d{2})\b", s)
    if m:
        return int(m.group(1)), 6  # assume metà anno se manca il mese
    return None


def _freshness(periodo: str | None) -> dict:
    """Classifica un'analisi in base a quanto è recente la data."""
    ym = _parse_periodo(periodo)
    if not ym:
        return {"label": "n/d", "level": "unknown", "color": "#94a3b8",
                "months_old": None, "iso": None, "periodo": periodo}
    y, m = ym
    from datetime import date
    today = date.today()
    months_old = (today.year - y) * 12 + (today.month - m)
    if months_old < 0:
        months_old = 0
    if months_old <= FRESH_MAX_MONTHS:
        label, level, color = "nuova", "fresh", "#16a34a"
    elif months_old <= FRESH_WARN_MONTHS:
        label, level, color = "in scadenza", "warn", "#f59e0b"
    else:
        label, level, color = "vecchia", "stale", "#dc2626"
    return {
        "label": label, "level": level, "color": color,
        "months_old": months_old,
        "iso": f"{y:04d}-{m:02d}",
        "periodo": periodo,
    }


def _build_enriched_geojson() -> dict:
    global _GEOJSON_CACHE
    if _GEOJSON_CACHE is not None:
        return _GEOJSON_CACHE
    from zone_names import enrich_zone

    # Unisce tutti i GeoJSON disponibili in un singolo FeatureCollection.
    merged_features: list[dict] = []
    name_to_provider: dict[str, str] = {}
    for prov_id, gf in GEOJSON_FILES.items():
        if not gf.exists():
            continue
        try:
            data = json.loads(gf.read_text(encoding="utf-8"))
        except Exception:
            continue
        for feat in data.get("features", []):
            p = feat.setdefault("properties", {})
            n = p.get("name")
            if not n:
                continue
            name_to_provider.setdefault(n, prov_id)
            # Marca subito il provider sulla feature (sovrascrive eventuali default).
            # Se la feature porta già `provider` (es. abruzzo_cam vs abruzzo_ruzzo),
            # rispettalo: rappresenta il sub-gestore reale.
            p["_source_provider"] = p.get("provider") or prov_id
            merged_features.append(feat)

    raw = {"type": "FeatureCollection", "features": merged_features}
    for feat in raw["features"]:
        p = feat.setdefault("properties", {})
        name = p.get("name")
        r = _RESULTS.get(name)
        prov_id = r.get("provider") if r else None
        prov_id = prov_id or p.get("_source_provider") or "acea_ato2"
        if r:
            summ = r.get("summary", {})
            p["status"] = summ.get("status", "OK")
            p["exceedances_count"] = len(summ.get("exceedances") or [])
            p["periodo"] = r.get("periodo")
            p["zona_label"] = r.get("zona")
            p["provider"] = prov_id
            p["freshness"] = _freshness(r.get("periodo"))
        else:
            p["status"] = "UNKNOWN"
            p["exceedances_count"] = 0
            p["provider"] = prov_id
            p["freshness"] = _freshness(None)
        # Metadati gestore (label corto + ATO) per badge UI.
        meta = PROVIDER_META.get(p["provider"]) or {}
        p["provider_label"] = (meta.get("label") or "").split(" — ")[0]
        p["provider_ato"] = meta.get("ato") or ""
        # Enrichment: nomi user-friendly + acquedotto + area geografica.
        # ATO 5 espone LOCALITA/DESCRIZ: usali come fallback per comune/zona.
        comune_hint = p.get("comune") or p.get("LOCALITA") or (r.get("comune") if r else None)
        zona_hint = p.get("zona_label") or p.get("DESCRIZ") or (r.get("zona") if r else None)
        enr = enrich_zone(name or "", comune_hint, zona_hint)
        p["display_name"] = enr["display_name"]
        p["area"] = enr.get("area") or ""
        p["aqueduct"] = enr.get("aqueduct") or ""
        p["aqueduct_hint"] = enr.get("aqueduct_hint") or ""
        p["zone_num"] = enr.get("zone_num") or ""
        p["icon"] = enr.get("icon") or "🏘️"
        p["badges"] = enr.get("badges") or []
        p["comune_label"] = enr.get("comune_label") or comune_hint
        p["search_tokens"] = enr.get("search_tokens") or ""
        # color by status (overrides Acea default which is uniform).
        status_color = {
            "OK": "#16a34a",
            "ATTENZIONE": "#dc2626",
            "INFORMATIVO": "#0284c7",
            "UNKNOWN": "#94a3b8",
        }.get(p["status"], "#94a3b8")
        p["fill"] = status_color
        p["stroke"] = status_color
    _GEOJSON_CACHE = raw
    return raw


# ---------- routes ----------
def _serialized_geojson() -> tuple[bytes, bytes]:
    """Ritorna (json_bytes, gz_bytes) della FeatureCollection arricchita.
    Ribuild solo quando cambia il giorno (freshness dipende dalla data).
    Thread-safe; protetto da lock per evitare doppio build sotto carico."""
    today = date.today()
    cached_date = _GEOJSON_RESP_CACHE.get("date")
    if (cached_date == today and _GEOJSON_RESP_CACHE.get("json_bytes")
            and _GEOJSON_RESP_CACHE.get("gz_bytes")):
        return _GEOJSON_RESP_CACHE["json_bytes"], _GEOJSON_RESP_CACHE["gz_bytes"]
    with _GEOJSON_RESP_LOCK:
        # Double-check after acquiring lock
        if (_GEOJSON_RESP_CACHE.get("date") == today
                and _GEOJSON_RESP_CACHE.get("json_bytes")
                and _GEOJSON_RESP_CACHE.get("gz_bytes")):
            return (_GEOJSON_RESP_CACHE["json_bytes"],
                    _GEOJSON_RESP_CACHE["gz_bytes"])
        data = _build_enriched_geojson()
        # Ricalcola freshness una sola volta per giorno.
        for feat in data.get("features", []):
            p = feat.get("properties") or {}
            p["freshness"] = _freshness(p.get("periodo"))
        json_bytes = json.dumps(
            data, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        gz_bytes = gzip.compress(json_bytes, compresslevel=6)
        _GEOJSON_RESP_CACHE["date"] = today
        _GEOJSON_RESP_CACHE["json_bytes"] = json_bytes
        _GEOJSON_RESP_CACHE["gz_bytes"] = gz_bytes
        # Le richieste vengono servite dai byte cache-ati: il dict parsato delle
        # geometrie (decine di MB) non serve più finché non si ricostruisce il
        # giorno dopo. Liberarlo tiene la memoria sotto il limite di Render (512MB).
        global _GEOJSON_CACHE
        _GEOJSON_CACHE = None
        data = None
        gc.collect()
        return json_bytes, gz_bytes


@app.get("/api/geojson")
def api_geojson():
    json_bytes, gz_bytes = _serialized_geojson()
    accept_enc = (request.headers.get("Accept-Encoding") or "").lower()
    if "gzip" in accept_enc:
        resp = Response(gz_bytes, mimetype="application/json")
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Content-Length"] = str(len(gz_bytes))
    else:
        resp = Response(json_bytes, mimetype="application/json")
        resp.headers["Content-Length"] = str(len(json_bytes))
    resp.headers["Cache-Control"] = "public, max-age=300"
    resp.headers["Vary"] = "Accept-Encoding"
    return resp


@app.get("/api/zone/<name>")
def api_zone(name: str):
    r = _RESULTS.get(name)
    if not r:
        abort(404, description=f"zone '{name}' not found")
    from zone_names import enrich_zone
    enr = enrich_zone(name, r.get("comune"), r.get("zona"))
    prov_id = r.get("provider", "acea_ato2")
    return jsonify({
        **r,
        "pdf_url": f"/api/pdf/{name}",
        "enrichment": enr,
        "freshness": _freshness(r.get("periodo")),
        "provider": prov_id,
        "provider_meta": PROVIDER_META.get(prov_id) or {},
    })


@app.get("/api/pdf/<name>")
def api_pdf(name: str):
    target = (PDF_DIR / f"{name}.pdf").resolve()
    if PDF_DIR.resolve() not in target.parents or not target.exists():
        abort(404)
    return send_file(target, mimetype="application/pdf")


# ---------- Gemini news (multi-topic, grounded, geocoded) ----------
# IMPORTANTE: ogni fetch costa molto (N chiamate parallele a Gemini Pro con
# grounding Google Search). Per evitare di bruciare credito a ogni utente
# che apre l'app, le news sono:
#   - condivise GLOBALMENTE (singolo stato server-side, non per-utente);
#   - persistite su disco (sopravvivono ai cold-start di Render);
#   - aggiornate al massimo una volta ogni NEWS_TTL_SECONDS (default 6h)
#     con strategia stale-while-revalidate (serve cache vecchia subito,
#     scatena un solo refresh in background, protetto da lock);
#   - `?fresh=1` accettato SOLO con header X-Admin-Token == NEWS_ADMIN_TOKEN.
from news_engine import (  # noqa: E402
    fetch_news, CATEGORY_META, load_news_cache, save_news_cache,
)

NEWS_TTL_SECONDS = int(os.environ.get("NEWS_TTL_SECONDS", str(15 * 60)))
NEWS_ADMIN_TOKEN = os.environ.get("NEWS_ADMIN_TOKEN", "")

_news_state: dict = {"data": None, "ts": 0.0, "refreshing": False}
_news_lock = threading.Lock()

# Hydrate cache da disco all'avvio: così dopo un cold start di Render
# le news sono subito disponibili senza chiamare Gemini.
_disk_cache = load_news_cache()
if _disk_cache and _disk_cache.get("items"):
    _news_state["data"] = _disk_cache
    _news_state["ts"] = float(_disk_cache.get("generated_at") or 0)


def _news_do_refresh() -> None:
    """Esegue una fetch completa e aggiorna stato + disco. Solo per uso interno."""
    try:
        data = fetch_news(limit_per_topic=4)
        if data.get("items"):
            data["generated_at"] = int(time.time())
            save_news_cache(data)
            with _news_lock:
                _news_state["data"] = data
                _news_state["ts"] = float(data["generated_at"])
    except Exception as e:  # noqa: BLE001 - non vogliamo crashare il thread
        print(f"[news] background refresh failed: {e}", file=sys.stderr)
    finally:
        with _news_lock:
            _news_state["refreshing"] = False


def _get_news(force: bool = False) -> dict:
    now = time.time()
    with _news_lock:
        data = _news_state["data"]
        ts = _news_state["ts"]
        refreshing = _news_state["refreshing"]
        age = (now - ts) if ts else float("inf")
        need_refresh = force or data is None or age > NEWS_TTL_SECONDS
        spawn_bg = False
        run_sync = False
        if need_refresh and not refreshing:
            _news_state["refreshing"] = True
            if data is None:
                run_sync = True  # primo avvio assoluto: serve qualcosa subito
            else:
                spawn_bg = True

    if run_sync:
        _news_do_refresh()
        with _news_lock:
            data = _news_state["data"]
            ts = _news_state["ts"]
    elif spawn_bg:
        threading.Thread(target=_news_do_refresh, daemon=True).start()

    out = dict(data or {"items": [], "categories": CATEGORY_META})
    out["cached"] = True
    out["generated_at"] = int(ts) if ts else None
    out["ttl_seconds"] = NEWS_TTL_SECONDS
    out["next_refresh_at"] = int(ts + NEWS_TTL_SECONDS) if ts else None
    with _news_lock:
        out["refreshing"] = _news_state["refreshing"]
    return out


@app.get("/api/news")
def api_news():
    # `fresh=1` è ammesso solo se chi chiama presenta un token admin.
    # Questo impedisce agli utenti del frontend di forzare chiamate AI costose.
    force = False
    if request.args.get("fresh") == "1":
        token = request.headers.get("X-Admin-Token", "")
        force = bool(NEWS_ADMIN_TOKEN) and token == NEWS_ADMIN_TOKEN
    limit = int(request.args.get("limit", 0) or 0)
    category = (request.args.get("category") or "").strip().lower()
    data = _get_news(force=force)
    items = list(data.get("items") or [])
    if category and category != "tutte":
        items = [it for it in items if it.get("category") == category]
    if limit > 0:
        items = items[:limit]
    return jsonify({**data, "items": items})


@app.get("/api/news/categories")
def api_news_categories():
    return jsonify(CATEGORY_META)


# ---------- Extras Roma: nasoni + acquedotti ----------
from roma_extras import get_nasoni, get_aqueducts  # noqa: E402


@app.get("/api/nasoni")
def api_nasoni():
    force = request.args.get("force", "0") == "1"
    return jsonify(get_nasoni(force=force))


@app.get("/api/aqueducts")
def api_aqueducts():
    return jsonify(get_aqueducts())


# ---------- Analytics + Search + AI Q&A + Compare ----------
from analytics import (  # noqa: E402
    build_dashboard, parameter_map, list_parameters, search as _search,
    compare as _compare, ask_ai,
)

_dashboard_cache: dict = {"ts": 0.0, "data": None}


@app.get("/api/dashboard")
def api_dashboard():
    if _dashboard_cache["data"] and (time.time() - _dashboard_cache["ts"]) < 300:
        return jsonify(_dashboard_cache["data"])
    d = build_dashboard()
    _dashboard_cache.update({"ts": time.time(), "data": d})
    return jsonify(d)


@app.get("/api/parameters")
def api_parameters():
    return jsonify({"items": list_parameters()})


@app.get("/api/parameter/<path:name>")
def api_parameter(name: str):
    return jsonify(parameter_map(name))


@app.get("/api/search")
def api_search():
    q = request.args.get("q", "")
    limit = max(1, min(int(request.args.get("limit", 20)), 50))
    return jsonify(_search(q, limit=limit))


@app.get("/api/compare")
def api_compare():
    names_arg = request.args.get("names", "")
    names = [n for n in names_arg.split(",") if n]
    if not names:
        return jsonify({"zones": [], "parameters": []})
    return jsonify(_compare(names))


@app.post("/api/ask")
def api_ask():
    body = request.get_json(force=True, silent=True) or {}
    q = (body.get("question") or request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "empty question"}), 400
    return jsonify(ask_ai(q))


# ---------- Fonti ufficiali esterne (Salute, G3W) ----------
from external_sources import OFFICIAL_SOURCES, PROVIDER_META  # noqa: E402


@app.get("/api/sources")
def api_sources():
    return jsonify({"items": OFFICIAL_SOURCES})


# ---------- Dati reali esterni: meteo ----------
from realtime import get_meteo  # noqa: E402


@app.get("/api/meteo")
def api_meteo():
    try:
        return jsonify(get_meteo())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ---------- frontend ----------
def _no_cache(resp):
    """Disabilita la cache del browser su index/CSS/JS per evitare versioni stantie."""
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.get("/")
def index():
    return _no_cache(send_from_directory(FRONTEND_DIR, "index.html"))


@app.get("/<path:fname>")
def static_files(fname: str):
    target = (FRONTEND_DIR / fname).resolve()
    if FRONTEND_DIR.resolve() not in target.parents and target != FRONTEND_DIR.resolve():
        abort(404)
    if not target.exists() or target.is_dir():
        abort(404)
    resp = send_from_directory(FRONTEND_DIR, fname)
    # Niente cache su asset front-end: in dev/sviluppo evita problemi di file vecchi.
    if fname.endswith((".html", ".css", ".js")):
        resp = _no_cache(resp)
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False)
