"""Scraper GAIA S.p.A. (Toscana — Lucca/Massa-Carrara/Pistoia).

Il portale https://www.gaia-spa.it/analisiweb_v2/ NON pubblica PDF sul server:
i referti vengono generati lato-client (DataTables/jsPDF) a partire da una
tabella HTML per ogni punto di prelievo.

Questo script:
  1. legge l'elenco completo dei punti di prelievo dal menu a tendina
     `#select_localita` della pagina principale (optgroup = comune);
  2. per ogni punto scarica la pagina `campioni/<cp>/<cp1>` e ne estrae
     comune, localita, periodo di riferimento e la tabella dei parametri
     (Parametri / Unita di Misura / Valore Medio / Limiti Normativi);
  3. genera un PDF per ogni punto in  backend/gaia_pdf/<comune>/<localita>.pdf

Uso:
    python backend/scrape_gaia.py            # scarica tutto (497 punti)
    python backend/scrape_gaia.py --limit 5  # solo i primi 5 (test)
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time
from pathlib import Path

import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

BASE = "https://www.gaia-spa.it/analisiweb_v2"
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "gaia_pdf"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AcquaMap-scraper/1.0 "
        "(qualita-acqua; contatto: acquamap)"
    )
}

_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)


def _get(url: str, retries: int = 4) -> str:
    """GET con retry/backoff."""
    last = None
    for attempt in range(retries):
        try:
            r = _SESSION.get(url, timeout=30)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:  # noqa: PERF203
            last = str(e)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET fallito {url}: {last}")


def _slug(s: str) -> str:
    s = html.unescape(s).strip().lower()
    s = re.sub(r"[àáâ]", "a", s)
    s = re.sub(r"[èé]", "e", s)
    s = re.sub(r"[ìí]", "i", s)
    s = re.sub(r"[òó]", "o", s)
    s = re.sub(r"[ùú]", "u", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "n_a"


def _clean(s: str) -> str:
    """Decodifica entita HTML e normalizza spazi."""
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


# ---------------------------------------------------------------------------
# 1. elenco punti di prelievo
# ---------------------------------------------------------------------------
def discover_points() -> list[dict]:
    """Ritorna [{comune, localita, cp, cp1, area}] per ogni punto di prelievo."""
    page = _get(f"{BASE}/")
    # isola il <select id="select_localita"> ... </select>
    m = re.search(r'id="select_localita".*?</select>', page, re.S)
    if not m:
        raise RuntimeError("menu select_localita non trovato")
    block = m.group(0)

    points: list[dict] = []
    current_comune = "N/A"
    # scorre optgroup (comune) e option (punto) in ordine di apparizione
    token_re = re.compile(
        r'<optgroup label="([^"]+)"'
        r'|<option value="[^"]*"\s+data-codice_comune="(\d+)"'
        r'\s+data-codice_prelievo="([^"]*)"'
        r'\s+data-codice_prelievo1="([^"]*)"'
        r'\s+data-codice_area="([^"]*)"\s*>([^<]*)</option>',
        re.S,
    )
    for t in token_re.finditer(block):
        if t.group(1) is not None:
            current_comune = _clean(t.group(1))
            continue
        points.append(
            {
                "comune": current_comune,
                "codice_comune": t.group(2),
                "cp": t.group(3),
                "cp1": t.group(4),
                "area": t.group(5),
                "localita": _clean(t.group(6)),
            }
        )
    return points


# ---------------------------------------------------------------------------
# 2. parsing pagina campioni
# ---------------------------------------------------------------------------
_ROW_RE = re.compile(
    r"<tr>\s*"
    r"<td><span[^>]*>(.*?)</span></td>\s*"
    r"<td>(.*?)</td>\s*"
    r"<td>(.*?)</td>\s*"
    r"<td>(.*?)</td>\s*"
    r"</tr>",
    re.S,
)


def fetch_campioni(cp: str, cp1: str) -> dict:
    """Scarica e parsa la pagina campioni di un punto di prelievo."""
    page = _get(f"{BASE}/campioni/{cp}/{cp1}")

    periodo = ""
    pm = re.search(r"Periodo di riferimento:\s*([^<]+)", page)
    if pm:
        periodo = _clean(pm.group(1))

    rows = []
    for r in _ROW_RE.finditer(page):
        param = _clean(r.group(1))
        unita = _clean(r.group(2))
        valore = _clean(r.group(3))
        limite = _clean(r.group(4))
        if param:
            rows.append((param, unita, valore, limite))

    return {
        "periodo": periodo,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 3. generazione PDF
# ---------------------------------------------------------------------------
_styles = getSampleStyleSheet()
_title_style = ParagraphStyle(
    "GaiaTitle", parent=_styles["Title"], fontSize=15, spaceAfter=4,
    textColor=colors.HexColor("#0b5394"),
)
_sub_style = ParagraphStyle(
    "GaiaSub", parent=_styles["Normal"], fontSize=10,
    textColor=colors.HexColor("#444444"),
)
_meta_style = ParagraphStyle(
    "GaiaMeta", parent=_styles["Normal"], fontSize=11, spaceBefore=6,
    spaceAfter=2,
)
_cell_style = ParagraphStyle(
    "GaiaCell", parent=_styles["Normal"], fontSize=8.5, leading=10,
)
_head_cell_style = ParagraphStyle(
    "GaiaHeadCell", parent=_styles["Normal"], fontSize=9, leading=11,
    textColor=colors.white, fontName="Helvetica-Bold",
)


def build_pdf(point: dict, data: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"GAIA - {point['comune']} - {point['localita']}",
        author="GAIA S.p.A.",
    )
    story = []
    story.append(Paragraph("GAIA S.p.A. — Qualità dell'acqua", _title_style))
    story.append(Paragraph(
        "Laboratorio analisi acque potabili e reflue (accreditamento ACCREDIA 01780)",
        _sub_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Comune:</b> {point['comune']}", _meta_style))
    story.append(Paragraph(f"<b>Località:</b> {point['localita']}", _meta_style))
    if data["periodo"]:
        story.append(Paragraph(
            f"<b>Periodo di riferimento:</b> {data['periodo']}", _meta_style))
    story.append(Spacer(1, 10))

    head = ["Parametri", "Unità di Misura", "Valore Medio", "Limiti Normativi"]
    table_data = [[Paragraph(h, _head_cell_style) for h in head]]
    for param, unita, valore, limite in data["rows"]:
        table_data.append([
            Paragraph(param, _cell_style),
            Paragraph(unita, _cell_style),
            Paragraph(valore, _cell_style),
            Paragraph(limite, _cell_style),
        ])

    tbl = Table(table_data, colWidths=[62 * mm, 33 * mm, 30 * mm, 49 * mm],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b5394")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b0b0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#eef4fb")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Fonte: GAIA S.p.A. — https://www.gaia-spa.it/analisiweb_v2/ "
        "(valori medi del periodo indicato).", _sub_style))
    doc.build(story)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="numero massimo di punti (0 = tutti)")
    ap.add_argument("--delay", type=float, default=0.4,
                    help="pausa tra le richieste (s)")
    args = ap.parse_args()

    print("[1/2] elenco punti di prelievo…")
    points = discover_points()
    print(f"   trovati {len(points)} punti in "
          f"{len({p['comune'] for p in points})} comuni")
    if args.limit:
        points = points[: args.limit]
        print(f"   --limit: scarico solo {len(points)} punti")

    print("[2/2] download + generazione PDF…")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    empty = 0
    errors: list[str] = []
    for i, p in enumerate(points, 1):
        out_path = (OUT_DIR / _slug(p["comune"]) /
                    f"{_slug(p['localita'])}.pdf")
        try:
            data = fetch_campioni(p["cp"], p["cp1"])
            if not data["rows"]:
                empty += 1
                print(f"   . {p['comune']} / {p['localita']}  (nessun dato)")
            else:
                build_pdf(p, data, out_path)
                ok += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"{p['comune']}/{p['localita']}: {e}")
            print(f"   ! {p['comune']} / {p['localita']}  ERRORE: {e}")
        if i % 25 == 0:
            print(f"   …{i}/{len(points)}  (ok={ok} vuoti={empty} err={len(errors)})")
        time.sleep(args.delay)

    print(f"\nFatto: {ok} PDF generati in {OUT_DIR}")
    if empty:
        print(f"   {empty} punti senza dati pubblicati")
    if errors:
        print(f"   {len(errors)} errori:")
        for e in errors[:15]:
            print(f"     - {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
