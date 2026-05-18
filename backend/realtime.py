"""
Dati reali in tempo reale per HydroMap.

Fonti utilizzate:
  - Open-Meteo (https://open-meteo.com) → archive-api per precipitazioni storiche
    e api per forecast 7 giorni. Servizio gratuito senza chiave.
  - Wikidata / dati pubblici per le caratteristiche del Lago di Bracciano
    (principale bacino di approvvigionamento idrico di Roma fino al 2017).

Tutti gli endpoint sono cache-ati su disco per ridurre il traffico.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / "realtime_cache.json"
CACHE_TTL = 3 * 60 * 60  # 3 ore

# Coordinate di riferimento (Campidoglio, Roma).
ROMA_LAT = 41.8933
ROMA_LON = 12.4830

# Lago di Bracciano (centro lago).
BRACCIANO_LAT = 42.117
BRACCIANO_LON = 12.233


# --------------------------------------------------------------------------- #
# Cache helpers
# --------------------------------------------------------------------------- #

def _load_cache() -> dict[str, Any]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(c: dict[str, Any]) -> None:
    CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def _cached(key: str, builder, ttl: int = CACHE_TTL) -> Any:
    c = _load_cache()
    entry = c.get(key)
    now = time.time()
    if entry and (now - entry.get("ts", 0)) < ttl:
        return entry["data"]
    try:
        data = builder()
    except Exception as e:
        # In caso di errore restituiamo l'eventuale cache scaduta
        if entry:
            return entry["data"]
        raise
    c[key] = {"ts": now, "data": data}
    _save_cache(c)
    return data


# --------------------------------------------------------------------------- #
# Open-Meteo
# --------------------------------------------------------------------------- #

def _fetch_open_meteo() -> dict[str, Any]:
    """Recupera precipitazioni storiche + forecast 7 giorni da Open-Meteo."""

    today = date.today()
    start_archive = today - timedelta(days=380)
    # L'archive-api ha latenza ~5 giorni → fine archivio = today - 5
    end_archive = today - timedelta(days=5)

    archive_url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={ROMA_LAT}&longitude={ROMA_LON}"
        f"&start_date={start_archive.isoformat()}"
        f"&end_date={end_archive.isoformat()}"
        "&daily=precipitation_sum,temperature_2m_mean"
        "&timezone=Europe%2FRome"
    )
    forecast_url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={ROMA_LAT}&longitude={ROMA_LON}"
        "&daily=precipitation_sum,temperature_2m_max,temperature_2m_min,"
        "weather_code"
        "&forecast_days=7&timezone=Europe%2FRome"
    )

    a = requests.get(archive_url, timeout=30).json()
    f = requests.get(forecast_url, timeout=20).json()

    a_dates = a["daily"]["time"]
    a_prec = a["daily"]["precipitation_sum"]
    a_temp = a["daily"]["temperature_2m_mean"]

    def _sum_last(n: int) -> float:
        vals = [v for v in a_prec[-n:] if v is not None]
        return round(sum(vals), 1)

    def _mean_last(n: int, src: list[float]) -> float | None:
        vals = [v for v in src[-n:] if v is not None]
        if not vals:
            return None
        return round(statistics.mean(vals), 2)

    # SPI semplificato: confronto pioggia 90gg vs media climatologica
    # stimata sui 365 giorni precedenti (rolling).
    rain_90 = _sum_last(90)
    rain_365 = _sum_last(365)
    expected_90 = rain_365 / 365 * 90 if rain_365 else 0
    drought_ratio = (rain_90 / expected_90) if expected_90 > 0 else None

    if drought_ratio is None:
        drought_label, drought_color = "n/d", "#94a3b8"
    elif drought_ratio < 0.5:
        drought_label, drought_color = "siccità severa", "#dc2626"
    elif drought_ratio < 0.75:
        drought_label, drought_color = "siccità moderata", "#ea580c"
    elif drought_ratio < 0.9:
        drought_label, drought_color = "lieve deficit", "#f59e0b"
    elif drought_ratio < 1.15:
        drought_label, drought_color = "regime normale", "#16a34a"
    else:
        drought_label, drought_color = "surplus pluviometrico", "#0284c7"

    # Serie storica giornaliera ultimi 90 giorni (per chart)
    series = [
        {"date": d, "rain": p if p is not None else 0.0,
         "temp": t if t is not None else None}
        for d, p, t in zip(a_dates[-90:], a_prec[-90:], a_temp[-90:])
    ]

    # Forecast giornaliero 7gg
    forecast = [
        {
            "date": d,
            "rain": p if p is not None else 0.0,
            "tmax": tmax,
            "tmin": tmin,
            "weather_code": wc,
        }
        for d, p, tmax, tmin, wc in zip(
            f["daily"]["time"],
            f["daily"]["precipitation_sum"],
            f["daily"]["temperature_2m_max"],
            f["daily"]["temperature_2m_min"],
            f["daily"]["weather_code"],
        )
    ]

    return {
        "source": "Open-Meteo (open-meteo.com)",
        "location": {"lat": ROMA_LAT, "lon": ROMA_LON, "label": "Roma Capitolino"},
        "updated": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "archive_range": {"start": a_dates[0], "end": a_dates[-1]},
        "rain_mm": {
            "last_7d": _sum_last(7),
            "last_30d": _sum_last(30),
            "last_90d": rain_90,
            "last_365d": rain_365,
            "expected_90d_from_365d_mean": round(expected_90, 1),
        },
        "temp_c": {
            "mean_last_30d": _mean_last(30, a_temp),
            "mean_last_365d": _mean_last(365, a_temp),
        },
        "drought": {
            "ratio_90d_vs_normal": (
                round(drought_ratio, 2) if drought_ratio is not None else None
            ),
            "label": drought_label,
            "color": drought_color,
        },
        "history_90d": series,
        "forecast_7d": forecast,
    }


def get_meteo() -> dict[str, Any]:
    return _cached("meteo", _fetch_open_meteo, ttl=3 * 3600)


# --------------------------------------------------------------------------- #
# Lago di Bracciano (dati pubblici Wikidata + sintesi tecniche ARPA Lazio)
# --------------------------------------------------------------------------- #

BRACCIANO_STATIC: dict[str, Any] = {
    "source": "Wikidata Q207692 + ARPA Lazio + ISPRA",
    "name": "Lago di Bracciano",
    "type": "lago vulcanico (caldera)",
    "lat": BRACCIANO_LAT,
    "lon": BRACCIANO_LON,
    "elevation_m": 164,
    "surface_km2": 56.5,
    "depth_max_m": 165,
    "depth_mean_m": 89,
    "volume_km3": 5.0,
    "shore_km": 31.5,
    "catchment_km2": 147.7,
    "main_inflow": "piccoli affluenti perimetrali (Lerre, Bagno, Grottoni)",
    "main_outflow": "Fiume Arrone",
    "shore_comuni": ["Bracciano", "Anguillara Sabazia", "Trevignano Romano"],
    "use": (
        "Riserva idropotabile storica di Roma: alimentava la Capitale "
        "fino al 2017 tramite l'acquedotto Paolo (presa di Anguillara). "
        "Dopo la siccità 2017 la captazione è stata limitata; "
        "Roma è oggi alimentata principalmente dall'acquedotto "
        "Peschiera-Capore (≈70%)."
    ),
    "protected_area": "Parco Naturale Regionale di Bracciano-Martignano (RM)",
    "wikipedia": "https://it.wikipedia.org/wiki/Lago_di_Bracciano",
    "wikidata": "https://www.wikidata.org/wiki/Q207692",
    # Soglie di allarme storiche (livello rispetto allo zero idrometrico
    # di Anguillara, fonte: ACEA / ARPA Lazio, 2017-2024).
    "level_zero_m": 0.0,
    "warning_levels": {
        "normal_min": -0.5,
        "attention": -1.0,
        "alarm": -1.5,
        "ban_extraction": -1.6,
    },
    "notes": (
        "Il minimo storico è stato registrato a fine luglio 2017 a "
        "−1,62 m sotto lo zero idrometrico, evento che portò alla "
        "sospensione delle captazioni ACEA e all'emergenza idrica "
        "di Roma."
    ),
}


def get_bracciano() -> dict[str, Any]:
    """Combina dati statici sul lago con dati meteo recenti."""
    out = dict(BRACCIANO_STATIC)
    try:
        m = get_meteo()
        out["recent_rain_30d_mm"] = m["rain_mm"]["last_30d"]
        out["recent_rain_90d_mm"] = m["rain_mm"]["last_90d"]
        out["drought_label"] = m["drought"]["label"]
        out["drought_color"] = m["drought"]["color"]
    except Exception:
        pass
    out["updated"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return out
