"""
Scrape: scarica il GeoJSON della mappa e tutti i PDF di qualità acqua
dal portale Acea Ato 2.
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://www.aceaato2.a-acqua.it"
GEOJSON_URL = f"{BASE}/content/dam/acea-ato2/json/mappa-qualita-ato-2.json"

ROOT = Path(__file__).parent / "data"
PDF_DIR = ROOT / "pdfs"
GEOJSON_FILE = ROOT / "mappa-qualita-ato-2.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": f"{BASE}/qualita-acqua",
}


def fix_pdf_link(link: str) -> str:
    """
    Il JSON contiene path con 'mappe-qualità' (con accento); il dispatcher
    serve invece la cartella 'mappe-qualita' (senza accento). Normalizza.
    """
    link = link.replace("mappe-qualità", "mappe-qualita")
    # Encode any remaining non-ASCII characters in path safely.
    return quote(link, safe="/:%")


def download_geojson(session: requests.Session) -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    print(f"[geojson] GET {GEOJSON_URL}")
    r = session.get(GEOJSON_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    GEOJSON_FILE.write_bytes(r.content)
    data = r.json()
    print(f"[geojson] saved -> {GEOJSON_FILE} ({len(data['features'])} features)")
    return data


def download_pdf(session: requests.Session, name: str, link: str) -> tuple[str, str]:
    target = PDF_DIR / f"{name}.pdf"
    if target.exists() and target.stat().st_size > 1024:
        return name, "cached"
    url = BASE + fix_pdf_link(link)
    for attempt in range(3):
        try:
            r = session.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith(
                "application/pdf"
            ):
                target.write_bytes(r.content)
                return name, "ok"
            if attempt == 2:
                return name, f"http {r.status_code}"
        except requests.RequestException as e:
            if attempt == 2:
                return name, f"err {e}"
        time.sleep(0.6 * (attempt + 1))
    return name, "fail"


def main() -> int:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    geo = download_geojson(session)

    # Dedup links: some zones might share a PDF (rare)
    tasks: dict[str, str] = {}
    for feat in geo["features"]:
        p = feat.get("properties") or {}
        name = p.get("name")
        link = p.get("link")
        if name and link:
            tasks.setdefault(name, link)

    print(f"[pdf] {len(tasks)} unique PDFs to fetch")

    results = {"ok": 0, "cached": 0, "fail": 0}
    failed: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(download_pdf, session, n, l) for n, l in tasks.items()]
        for i, fut in enumerate(as_completed(futures), 1):
            name, status = fut.result()
            if status in ("ok", "cached"):
                results[status] += 1
            else:
                results["fail"] += 1
                failed.append((name, status))
            if i % 25 == 0 or i == len(futures):
                print(f"  progress {i}/{len(futures)}  ok={results['ok']} cached={results['cached']} fail={results['fail']}")

    if failed:
        print("[pdf] FAILED:")
        for n, s in failed[:20]:
            print(f"  - {n}: {s}")
    print(f"[done] ok={results['ok']} cached={results['cached']} fail={results['fail']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
