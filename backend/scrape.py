"""
Scrape: scarica il GeoJSON della mappa e tutti i PDF di qualità acqua
dai portali Acea (ATO 2 — Roma, e ATO 5 — Frosinone, che usano lo
stesso template).

Utilizzo:
    python backend/scrape.py                       # default: acea_ato2
    python backend/scrape.py --provider acea_ato2
    python backend/scrape.py --provider acea_ato5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import requests

# Registry dei portali Acea con lo stesso template (Adobe Experience Manager).
# Lo schema delle properties varia leggermente tra ATO 2 e ATO 5:
#   - ATO 2: properties.link   (campo URL PDF)
#   - ATO 5: properties['Codice L_5'] (campo URL PDF)
PROVIDERS: dict[str, dict] = {
    "acea_ato2": {
        "label": "Acea ATO 2 — Roma e provincia",
        "base": "https://www.aceaato2.a-acqua.it",
        "geojson_path": "/content/dam/acea-ato2/json/mappa-qualita-ato-2.json",
        "geojson_file": "mappa-qualita-ato-2.json",
        "link_keys": ["link"],
    },
    "acea_ato5": {
        "label": "Acea ATO 5 — Frosinone e provincia",
        "base": "https://www.aceaato5.a-acqua.it",
        "geojson_path": "/content/dam/acea-ato5/json/mappa-qualita-ato-5.json",
        "geojson_file": "mappa-qualita-ato-5.json",
        "link_keys": ["Codice L_5", "link"],
    },
}

ROOT = Path(__file__).parent / "data"
PDF_DIR = ROOT / "pdfs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def fix_pdf_link(link: str) -> str:
    """
    Il JSON contiene path con 'mappe-qualità' (con accento); il dispatcher
    serve invece la cartella 'mappe-qualita' (senza accento). Normalizza.
    """
    link = link.replace("mappe-qualità", "mappe-qualita")
    # Encode any remaining non-ASCII characters in path safely.
    return quote(link, safe="/:%")


def download_geojson(session: requests.Session, prov: dict, geojson_file: Path) -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    url = prov["base"] + prov["geojson_path"]
    print(f"[geojson] GET {url}")
    r = session.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    geojson_file.write_bytes(r.content)
    data = r.json()
    print(f"[geojson] saved -> {geojson_file} ({len(data['features'])} features)")
    return data


def download_pdf(session: requests.Session, base: str, name: str, link: str) -> tuple[str, str]:
    target = PDF_DIR / f"{name}.pdf"
    if target.exists() and target.stat().st_size > 1024:
        return name, "cached"
    url = base + fix_pdf_link(link)
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
    ap = argparse.ArgumentParser(description="Scraper qualità acqua AcquaMap (Acea ATO 2/5)")
    ap.add_argument("--provider", choices=list(PROVIDERS.keys()), default="acea_ato2",
                    help="Gestore idrico da scaricare (default: acea_ato2)")
    args = ap.parse_args()
    prov = PROVIDERS[args.provider]
    geojson_file = ROOT / prov["geojson_file"]
    base = prov["base"]
    # Referer header dipende dal provider attivo.
    headers = dict(HEADERS, **{"Referer": f"{base}/qualita-acqua"})

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(headers)
    print(f"[provider] {args.provider}  {prov['label']}")
    geo = download_geojson(session, prov, geojson_file)

    # Dedup links: some zones might share a PDF (rare)
    link_keys = prov.get("link_keys") or ["link"]
    tasks: dict[str, str] = {}
    for feat in geo["features"]:
        p = feat.get("properties") or {}
        name = p.get("name")
        link = next((p[k] for k in link_keys if p.get(k)), None)
        if name and link:
            tasks.setdefault(name, link)

    print(f"[pdf] {len(tasks)} unique PDFs to fetch")

    results = {"ok": 0, "cached": 0, "fail": 0}
    failed: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(download_pdf, session, base, n, l) for n, l in tasks.items()]
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
