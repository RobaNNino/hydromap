"""
AcquaMap analytics & AI assistant.

Funzioni:
  - build_dashboard()  -> aggregati statistici sulle 275 zone
  - parameter_map()    -> mappa coropletica per un parametro
  - search()           -> ricerca full-text su zone, parametri, comuni
  - ask_ai()           -> risposta Q&A in linguaggio naturale via Gemini con
                          contesto numerico iniettato (RAG semplice)
"""
from __future__ import annotations
import json
import os
import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import requests

from zone_names import enrich_zone

DATA = Path(__file__).parent / "data"
RESULTS_FILE = DATA / "results.json"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _load() -> dict:
    if not RESULTS_FILE.exists():
        return {}
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------- DASHBOARD ----------
def build_dashboard() -> dict:
    res = _load()
    total = len(res)
    statuses = Counter()
    exc_by_param: Counter = Counter()
    exc_by_comune: Counter = Counter()
    params_seen: Counter = Counter()
    param_values: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    comuni: Counter = Counter()

    for name, r in res.items():
        s = (r.get("summary") or {}).get("status", "UNKNOWN")
        statuses[s] += 1
        comune = r.get("comune") or "?"
        comuni[comune] += 1
        for e in (r.get("summary") or {}).get("exceedances", []):
            exc_by_param[e.get("parametro", "?")] += 1
            exc_by_comune[comune] += 1
        for p in r.get("parameters") or []:
            pname = p.get("parametro")
            if not pname:
                continue
            params_seen[pname] += 1
            v = p.get("valore_num")
            l = p.get("limite_num")
            if isinstance(v, (int, float)):
                param_values[pname].append((name, float(v), float(l) if isinstance(l, (int, float)) else None))

    # statistiche per parametro (top per quantità di dati)
    param_stats = []
    for pname, vals in param_values.items():
        nums = [v for _, v, _ in vals]
        if not nums:
            continue
        nums_sorted = sorted(nums)
        n = len(nums_sorted)
        median = nums_sorted[n // 2] if n else 0
        param_stats.append({
            "parametro": pname,
            "count": n,
            "min": min(nums),
            "max": max(nums),
            "mean": sum(nums) / n,
            "median": median,
        })
    param_stats.sort(key=lambda x: -x["count"])

    return {
        "total_zones": total,
        "status_breakdown": dict(statuses),
        "top_exceedances_by_parameter": exc_by_param.most_common(15),
        "top_exceedances_by_comune": exc_by_comune.most_common(15),
        "top_comuni_by_zones": comuni.most_common(15),
        "parameter_stats": param_stats[:30],
        "total_parameters_distinct": len(params_seen),
        "generated_at": int(time.time()),
    }


# ---------- COROPLETICO PER PARAMETRO ----------
def parameter_map(param: str) -> dict:
    """Per ogni zona, restituisce nome + valore numerico del parametro richiesto."""
    res = _load()
    pkey = _norm(param)
    items = []
    nums = []
    for name, r in res.items():
        for p in r.get("parameters") or []:
            if _norm(p.get("parametro", "")) == pkey:
                v = p.get("valore_num")
                if isinstance(v, (int, float)):
                    enr = enrich_zone(name, r.get("comune"), r.get("zona"))
                    items.append({
                        "name": name,
                        "comune": r.get("comune"),
                        "zona": r.get("zona"),
                        "display_name": enr.get("display_name"),
                        "area": enr.get("area"),
                        "valore": v,
                        "limite": p.get("limite_num"),
                        "unita": p.get("unita"),
                    })
                    nums.append(float(v))
                break
    if nums:
        mn, mx = min(nums), max(nums)
        med = sorted(nums)[len(nums) // 2]
        avg = sum(nums) / len(nums)
    else:
        mn = mx = med = avg = None
    return {
        "parametro": param,
        "items": items,
        "count": len(items),
        "min": mn,
        "max": mx,
        "mean": avg,
        "median": med,
    }


def list_parameters() -> list[str]:
    res = _load()
    seen: Counter = Counter()
    for r in res.values():
        for p in r.get("parameters") or []:
            n = p.get("parametro")
            if n and isinstance(p.get("valore_num"), (int, float)):
                seen[n] += 1
    return [n for n, _ in seen.most_common(60)]


# ---------- SEARCH ----------
def search(q: str, limit: int = 25) -> dict:
    if not q or len(q.strip()) < 2:
        return {"q": q, "items": []}
    res = _load()
    qn = _norm(q)
    tokens = [t for t in qn.split() if t]
    if not tokens:
        return {"q": q, "items": []}
    matches = []
    for name, r in res.items():
        enr = enrich_zone(name, r.get("comune"), r.get("zona"))
        haystacks = {
            "name": _norm(name),
            "comune": _norm(r.get("comune", "")),
            "zona": _norm(r.get("zona", "")),
            "display": _norm(enr.get("display_name", "")),
            "area": _norm(enr.get("area", "")),
            "tokens": _norm(enr.get("search_tokens", "")),
            "params": " ".join(_norm(p.get("parametro", "")) for p in r.get("parameters") or []),
        }
        text = " ".join(haystacks.values())
        if not all(t in text for t in tokens):
            continue
        # score: weight by where it matches
        score = 0
        for t in tokens:
            if t in haystacks["display"]: score += 7
            if t in haystacks["area"]:    score += 6
            if t in haystacks["comune"]:  score += 5
            if t in haystacks["zona"]:    score += 3
            if t in haystacks["name"]:    score += 2
            if t in haystacks["tokens"]:  score += 2
            if t in haystacks["params"]:  score += 1
        matches.append({
            "name": name,
            "comune": r.get("comune"),
            "zona": r.get("zona"),
            "display_name": enr.get("display_name"),
            "area": enr.get("area"),
            "aqueduct": enr.get("aqueduct"),
            "icon": enr.get("icon"),
            "status": (r.get("summary") or {}).get("status"),
            "exceedances": len((r.get("summary") or {}).get("exceedances") or []),
            "score": score,
        })
    matches.sort(key=lambda x: -x["score"])
    return {"q": q, "items": matches[:limit], "total": len(matches)}


# ---------- COMPARE ----------
def compare(names: list[str]) -> dict:
    res = _load()
    zones = []
    all_params: list[str] = []
    seen = set()
    for n in names:
        r = res.get(n)
        if not r:
            continue
        enr = enrich_zone(n, r.get("comune"), r.get("zona"))
        zones.append({
            "name": n,
            "comune": r.get("comune"),
            "zona": r.get("zona"),
            "display_name": enr.get("display_name"),
            "area": enr.get("area"),
            "aqueduct": enr.get("aqueduct"),
            "icon": enr.get("icon"),
            "status": (r.get("summary") or {}).get("status"),
            "exceedances": (r.get("summary") or {}).get("exceedances") or [],
            "parameters": {p.get("parametro"): p for p in r.get("parameters") or []},
        })
        for p in r.get("parameters") or []:
            if p.get("parametro") and p.get("parametro") not in seen:
                seen.add(p.get("parametro"))
                all_params.append(p.get("parametro"))
    return {"zones": zones, "parameters": all_params}


# ---------- AI Q&A ----------
def _ai_context(question: str) -> str:
    """Costruisce un contesto compatto con i numeri rilevanti."""
    d = build_dashboard()
    res = _load()
    lines = []
    lines.append(f"Totale zone analizzate: {d['total_zones']}.")
    sb = d["status_breakdown"]
    lines.append(
        f"Stato: {sb.get('OK', 0)} conformi, {sb.get('ATTENZIONE', 0)} con anomalie, "
        f"{sb.get('UNKNOWN', 0)} senza dati."
    )

    # Zone con anomalie: dettaglio puntuale
    warn_zones = [(n, r) for n, r in res.items()
                  if (r.get("summary") or {}).get("status") == "ATTENZIONE"]
    if warn_zones:
        lines.append("Zone non conformi (dettaglio):")
        for n, r in warn_zones:
            excs = (r.get("summary") or {}).get("exceedances") or []
            ed = ", ".join(f"{e.get('parametro')}={e.get('valore')} (lim {e.get('limite')})"
                           for e in excs)
            lines.append(f"  - {r.get('comune')} / {r.get('zona')}: {ed}")

    # Per ogni parametro più presente, top 5 zone per valore
    lines.append("Top zone per valore di parametri chiave:")
    interesting = ["Arsenico", "Fluoruri", "Cloruri", "Sodio", "Nitrati",
                   "Piombo", "Nichel", "Manganese", "Somma di PFAS", "Conc. ioni idrogeno"]
    for pname in interesting:
        rows = []
        for n, r in res.items():
            for p in r.get("parameters") or []:
                if p.get("parametro") == pname and isinstance(p.get("valore_num"), (int, float)):
                    rows.append((r.get("comune"), r.get("zona"), p["valore_num"],
                                 p.get("limite"), p.get("unita")))
        if not rows:
            continue
        rows.sort(key=lambda x: -x[2])
        top = rows[:5]
        lines.append(
            f"  {pname} ({top[0][4] or ''}): " +
            "; ".join(f"{c}/{z}={v}" for c, z, v, _, _ in top)
        )

    lines.append("Top parametri con superamenti:")
    for p, c in d["top_exceedances_by_parameter"][:8]:
        lines.append(f"  - {p}: {c} zone")
    lines.append("Top comuni con superamenti:")
    for c, n in d["top_exceedances_by_comune"][:8]:
        lines.append(f"  - {c}: {n} zone")

    s = search(question, limit=6)
    if s["items"]:
        lines.append("Zone correlate alla domanda dell'utente:")
        for it in s["items"]:
            lines.append(
                f"  - {it['comune']} / {it['zona']}: stato={it['status']}, "
                f"anomalie={it['exceedances']}"
            )
    return "\n".join(lines)


def ask_ai(question: str) -> dict:
    if not GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY not set"}
    ctx = _ai_context(question)
    prompt = (
        "Sei un assistente esperto della qualità dell'acqua potabile in Italia, "
        "specializzato sulle 275 zone della rete Acea Ato 2 (Roma e provincia). "
        "Rispondi in italiano, in modo conciso e con dati numerici concreti. "
        "Se la domanda è fuori contesto, dillo brevemente. "
        "Usa solo i dati forniti qui sotto (NON inventare numeri). "
        "Cita sempre i nomi dei comuni/zone se rilevanti.\n\n"
        f"=== DATI ACQUAMAP ===\n{ctx}\n=== FINE DATI ===\n\n"
        f"Domanda dell'utente: {question}\n\nRisposta:"
    )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }
    for attempt in range(3):
        try:
            r = requests.post(url, json=body, timeout=60)
        except requests.RequestException as e:
            if attempt == 2:
                return {"error": str(e)}
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return {"answer": txt.strip(), "model": GEMINI_MODEL}
            except (KeyError, IndexError):
                return {"error": "Gemini empty response"}
        if r.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
    return {"error": "max retries"}
