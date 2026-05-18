"""
Parser: estrae i parametri di qualità dell'acqua da ogni PDF
e produce backend/data/results.json.
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).parent / "data"
PDF_DIR = ROOT / "pdfs"
GEOJSON_FILE = ROOT / "mappa-qualita-ato-2.json"
OUT_FILE = ROOT / "results.json"

SECTION_KEYS = (
    "Fonti di approvvigionamento",
    "Trattamenti",
    "Disinfezione",
    "Ordinanze di Non Potabilità",
)


def _clean(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def _parse_number(v: str) -> float | None:
    """Convert italian decimal strings like '17,5' or '<0,2' to float (best effort)."""
    if not v:
        return None
    s = v.strip().replace("\u00a0", "")
    if s in {"-", ""}:
        return None
    # Strip operators / units, keep number portion.
    m = re.search(r"[<>]?\s*([0-9]+(?:[.,][0-9]+)?)", s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def parse_pdf(path: Path) -> dict:
    """
    Returns:
        {
          "name": str,
          "comune": str|None,
          "zona": str|None,
          "periodo": str|None,
          "parameters": [{parametro, unita, limite, valore, valore_num}],
          "sections": {key: text},
          "summary": {compliant: int, total_with_limit: int, exceedances: [..]}
        }
    """
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {}}

    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""
        tables = page.extract_tables() or []

        # ---- metadata from text top ----
        m = re.search(r"COMUNE DI\s+([^\n]+)", text, re.IGNORECASE)
        out["comune"] = _clean(m.group(1)) if m else None
        m = re.search(r"\bZONA\s+([^\n]+)", text, re.IGNORECASE)
        out["zona"] = _clean(m.group(1)) if m else None
        m = re.search(
            r"(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|"
            r"agosto|settembre|ottobre|novembre|dicembre)\s+\d{4}",
            text,
            re.IGNORECASE,
        )
        out["periodo"] = _clean(m.group(0)) if m else None

        # ---- parameter table (first table with the expected header) ----
        param_table = None
        for t in tables:
            if not t:
                continue
            header = [_clean(c) for c in t[0]] if t[0] else []
            joined = " | ".join(header).lower()
            if "parametro" in joined and "valori" in joined:
                param_table = t
                break

        if param_table:
            for row in param_table[1:]:
                if not row or len(row) < 4:
                    continue
                parametro = _clean(row[0])
                unita = _clean(row[1])
                limite = _clean(row[2])
                valore = _clean(row[3])
                if not parametro:
                    continue
                out["parameters"].append(
                    {
                        "parametro": parametro,
                        "unita": unita,
                        "limite": limite,
                        "valore": valore,
                        "valore_num": _parse_number(valore),
                        "limite_num": _parse_number(limite),
                    }
                )

        # ---- right-column sections (descriptive blocks) ----
        for t in tables:
            for row in t:
                if not row:
                    continue
                head = _clean(row[0]) if row[0] else ""
                if head in SECTION_KEYS and len(row) == 1:
                    # next single-cell row likely contains content
                    idx = t.index(row)
                    if idx + 1 < len(t) and t[idx + 1]:
                        out["sections"][head] = _clean(t[idx + 1][0])

        # Fallback: parse sections from raw text if not found.
        if not out["sections"]:
            for key in SECTION_KEYS:
                m = re.search(
                    rf"{re.escape(key)}\s*\n(.+?)(?=\n(?:{'|'.join(map(re.escape, SECTION_KEYS))})\b|\Z)",
                    text,
                    re.DOTALL,
                )
                if m:
                    out["sections"][key] = _clean(m.group(1))

    # ---- summary / compliance ----
    exceed: list[dict] = []
    total_with_limit = 0
    for p in out["parameters"]:
        v = p["valore_num"]
        l = p["limite_num"]
        lim_raw = (p["limite"] or "").strip()
        val_raw = (p["valore"] or "").strip()
        # Skip ranges/descriptive limits (es. "6,5<pH< 9,5", "Senza variazioni anomale", "La somma <10")
        is_range = bool(re.search(r"\d.*[<>].*\d", lim_raw)) or any(
            kw in lim_raw.lower() for kw in ("senza", "somma", "ph", "anomale")
        )
        # Microbiological text "Non conforme".
        if val_raw.lower() == "non conforme":
            exceed.append(
                {"parametro": p["parametro"], "valore": p["valore"], "limite": p["limite"]}
            )
            continue
        if l is None or v is None or is_range:
            continue
        # The value string may contain "<" meaning "below detection limit": that's compliant.
        if val_raw.startswith("<"):
            total_with_limit += 1
            continue
        total_with_limit += 1
        # "Cloro residuo libero" usa il "valore di parametro" OMS (0,2 mg/L),
        # non un limite di legge: piccole eccedenze sono normali e non vanno
        # segnalate come anomalia.
        if "cloro residuo" in p["parametro"].lower():
            continue
        if v > l:
            exceed.append(
                {"parametro": p["parametro"], "valore": p["valore"], "limite": p["limite"]}
            )
    out["summary"] = {
        "total_parameters": len(out["parameters"]),
        "total_with_limit": total_with_limit,
        "exceedances": exceed,
        "status": "OK" if not exceed else "ATTENZIONE",
    }
    return out


def _worker(path_str: str) -> tuple[str, dict | str]:
    p = Path(path_str)
    try:
        return p.stem, parse_pdf(p)
    except Exception as e:  # pragma: no cover
        return p.stem, f"ERROR: {e!r}"


def main() -> int:
    if not GEOJSON_FILE.exists():
        print("Missing GeoJSON. Run scrape.py first.")
        return 1
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    print(f"[parse] {len(pdfs)} PDFs found")

    results: dict[str, dict] = {}
    errors: list[tuple[str, str]] = []

    with ProcessPoolExecutor() as pool:
        futures = {pool.submit(_worker, str(p)): p.stem for p in pdfs}
        for i, fut in enumerate(as_completed(futures), 1):
            name, res = fut.result()
            if isinstance(res, str):
                errors.append((name, res))
            else:
                results[name] = res
            if i % 25 == 0 or i == len(pdfs):
                print(f"  parsed {i}/{len(pdfs)}  errors={len(errors)}")

    OUT_FILE.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    print(f"[parse] wrote {OUT_FILE} ({len(results)} entries, {len(errors)} errors)")
    if errors:
        for n, e in errors[:10]:
            print(f"  ! {n}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
