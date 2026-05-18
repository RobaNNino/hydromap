"""
HydroMap backend.
Endpoints:
  GET  /                            -> serve frontend
  GET  /api/geojson                 -> map polygons with status+links
  GET  /api/zone/<name>             -> parsed PDF result + PDF passthrough URL
  GET  /api/pdf/<name>              -> stream PDF
  GET  /api/news?limit=5            -> latest Italian water news via Gemini grounding
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Permette gli import "flat" (from news_engine import ...) sia quando lanciamo
# `python backend/app.py` localmente, sia quando gunicorn lancia `backend.app:app`
# dalla root del progetto (in quel caso senza questa riga `news_engine` non si trova).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ROOT = Path(__file__).parent / "data"
PDF_DIR = ROOT / "pdfs"
GEOJSON_FILE = ROOT / "mappa-qualita-ato-2.json"
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


def _build_enriched_geojson() -> dict:
    global _GEOJSON_CACHE
    if _GEOJSON_CACHE is not None:
        return _GEOJSON_CACHE
    raw = json.loads(GEOJSON_FILE.read_text(encoding="utf-8"))
    for feat in raw["features"]:
        p = feat.setdefault("properties", {})
        name = p.get("name")
        r = _RESULTS.get(name)
        if r:
            summ = r.get("summary", {})
            p["status"] = summ.get("status", "OK")
            p["exceedances_count"] = len(summ.get("exceedances") or [])
            p["periodo"] = r.get("periodo")
            p["zona_label"] = r.get("zona")
        else:
            p["status"] = "UNKNOWN"
            p["exceedances_count"] = 0
        # color by status (overrides Acea default which is uniform).
        status_color = {
            "OK": "#16a34a",
            "ATTENZIONE": "#dc2626",
            "UNKNOWN": "#94a3b8",
        }[p["status"]]
        p["fill"] = status_color
        p["stroke"] = status_color
    _GEOJSON_CACHE = raw
    return raw


# ---------- routes ----------
@app.get("/api/geojson")
def api_geojson():
    return jsonify(_build_enriched_geojson())


@app.get("/api/zone/<name>")
def api_zone(name: str):
    r = _RESULTS.get(name)
    if not r:
        abort(404, description=f"zone '{name}' not found")
    return jsonify({**r, "pdf_url": f"/api/pdf/{name}"})


@app.get("/api/pdf/<name>")
def api_pdf(name: str):
    target = (PDF_DIR / f"{name}.pdf").resolve()
    if PDF_DIR.resolve() not in target.parents or not target.exists():
        abort(404)
    return send_file(target, mimetype="application/pdf")


# ---------- Gemini news (multi-topic, grounded, geocoded) ----------
from news_engine import fetch_news, CATEGORY_META  # noqa: E402

_news_cache: dict = {"ts": 0.0, "data": None}
_news_lock = __import__("threading").Lock()


def _get_news(fresh: bool, ttl: int = 900) -> dict:
    with _news_lock:
        if (not fresh and _news_cache["data"]
                and (time.time() - _news_cache["ts"]) < ttl):
            return {**_news_cache["data"], "cached": True}
    data = fetch_news(limit_per_topic=5)
    if data.get("items"):
        with _news_lock:
            _news_cache.update({"ts": time.time(), "data": data})
    return data


@app.get("/api/news")
def api_news():
    fresh = request.args.get("fresh", "0") == "1"
    limit = int(request.args.get("limit", 0) or 0)
    category = (request.args.get("category") or "").strip().lower()
    data = _get_news(fresh)
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


# ---------- Dati reali esterni: meteo + lago Bracciano ----------
from realtime import get_meteo, get_bracciano  # noqa: E402


@app.get("/api/meteo")
def api_meteo():
    try:
        return jsonify(get_meteo())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/bracciano")
def api_bracciano():
    try:
        return jsonify(get_bracciano())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ---------- frontend ----------
@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/<path:fname>")
def static_files(fname: str):
    target = (FRONTEND_DIR / fname).resolve()
    if FRONTEND_DIR.resolve() not in target.parents and target != FRONTEND_DIR.resolve():
        abort(404)
    if not target.exists() or target.is_dir():
        abort(404)
    return send_from_directory(FRONTEND_DIR, fname)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False)
