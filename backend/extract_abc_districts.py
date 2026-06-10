"""Estrae i 50 poligoni reali dei distretti ABC Napoli dalla mappa ufficiale.

Fonte: https://www.abc.napoli.it/jumi/poly.php  (mappa Google Maps con i
poligoni delle aree di prelievo). Ogni `obj_N` è l'anello di coordinate del
poligono; il relativo `balloon_N` contiene il codice distretto (es. "D22"),
il nome della zona (es. "Corso Chiaiano") e il link al PDF.

Output: backend/data/abc_napoli_districts.json
  { "D01": {"name": "...", "ring": [[lon,lat], ...]}, ... }
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "abc_napoli_districts.json"
SRC_URL = "https://www.abc.napoli.it/jumi/poly.php"
REFERER = ("https://www.abc.napoli.it/index.php?option=com_jumi"
           "&view=application&fileid=8&Itemid=316")


def fetch_html() -> str:
    cache = HERE.parent / "_poly_raw.html"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    h = {"User-Agent": "Mozilla/5.0", "Referer": REFERER}
    r = requests.get(SRC_URL, headers=h, timeout=60)
    r.raise_for_status()
    return r.text


def parse_objects(html: str) -> dict[int, list[list[float]]]:
    """obj_N = [ new google.maps.LatLng(lat,lng), ... ]  ->  ring [[lon,lat]]"""
    rings: dict[int, list[list[float]]] = {}
    for m in re.finditer(r"var\s+obj_(\d+)\s*=\s*\[(.*?)\];", html, re.S):
        idx = int(m.group(1))
        body = m.group(2)
        pts = re.findall(
            r"LatLng\(\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", body)
        ring = [[float(lng), float(lat)] for lat, lng in pts]
        if len(ring) >= 3:
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            rings[idx] = ring
    return rings


def parse_balloons(html: str) -> dict[int, dict]:
    """balloon_N -> {codice, nome, pdf}"""
    out: dict[int, dict] = {}
    for m in re.finditer(r"function\s+balloon_(\d+)\s*\(event\)\s*\{(.*?)\n\s*\}",
                          html, re.S):
        idx = int(m.group(1))
        body = m.group(2)
        cod = re.search(r"class=\"titolo\">([^<]+)<", body)
        nome = re.search(r"class=\"testo\">([^<]+)<", body)
        pdf = re.search(r"href=\"([^\"]+rptLab\.php\?pp=[^\"]+)\"", body)
        out[idx] = {
            "codice": (cod.group(1).strip() if cod else ""),
            "nome": (nome.group(1).strip() if nome else ""),
            "pdf": (pdf.group(1).strip() if pdf else ""),
        }
    return out


def main() -> None:
    html = fetch_html()
    rings = parse_objects(html)
    balloons = parse_balloons(html)
    print(f"poligoni: {len(rings)}  balloon: {len(balloons)}")

    districts: dict[str, dict] = {}
    for idx, ring in rings.items():
        b = balloons.get(idx, {})
        cod = b.get("codice") or f"OBJ{idx}"
        districts[cod] = {
            "name": b.get("nome", ""),
            "pdf": b.get("pdf", ""),
            "ring": ring,
        }
    # ordina per codice
    districts = dict(sorted(districts.items()))
    OUT.write_text(json.dumps(districts, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"scritto {OUT}  ({len(districts)} distretti)")
    miss = [c for c, v in districts.items() if not v["name"]]
    if miss:
        print("  senza nome:", miss)


if __name__ == "__main__":
    main()
