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
# I PDF Acea (ATO 2/5) sono tutti dentro PDF_DIR (nomi non collidono perché
# usano slug e codici diversi). Il provider è determinato dal GeoJSON di
# appartenenza.
GEOJSON_FILES = {
    "acea_ato2": ROOT / "mappa-qualita-ato-2.json",
    "acea_ato5": ROOT / "mappa-qualita-ato-5.json",
    "acqualatina": ROOT / "mappa-qualita-acqualatina.json",
    "acqua_pubblica_sabina": ROOT / "mappa-qualita-aps.json",
}
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
    """Convert italian decimal strings like '17,5', '<0,2', '1,1*10^3' to float.

    Supporta notazione scientifica italiana usata nei rapporti di prova del
    laboratorio Gruppo Maurizi (es. ``1,1*10^3`` → 1100.0).
    """
    if not v:
        return None
    s = v.strip().replace("\u00a0", "")
    if s in {"-", "", "/"}:
        return None
    # Notazione scientifica: "1,1*10^3" → 1.1 * 10^3 = 1100
    m_sci = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*\*\s*10\s*\^\s*(-?\d+)", s)
    if m_sci:
        try:
            mantissa = float(m_sci.group(1).replace(",", "."))
            return mantissa * (10 ** int(m_sci.group(2)))
        except ValueError:
            pass
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
        # Data analisi: prova prima il formato mese+anno (ATO 2),
        # poi il formato semestrale/trimestrale (ATO 5).
        m = re.search(
            r"(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|"
            r"agosto|settembre|ottobre|novembre|dicembre)\s+\d{4}",
            text,
            re.IGNORECASE,
        )
        if m:
            out["periodo"] = _clean(m.group(0))
        else:
            m = re.search(
                r"(primo|secondo|terzo|quarto|i+|iv)\s*(semestre|trimestre)\s+\d{4}",
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


def parse_pdf_acqualatina(path: Path) -> dict:
    """
    Parser dedicato per i PDF Acqualatina (schema diverso da Acea):
      - "Comune di X"
      - "Approvvigionamento ..." (più righe possibili)
      - "Punto di prelievo ..."
      - "Periodo di monitoraggio: II semestre 2025"
      - Tabella 4 colonne: Prova | Unità di misura | Limite (D.Lgs 31/01) | Valore
    Estraibile direttamente dal testo lineare con regex per riga.
    """
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {}}
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""

    lines = [ln for ln in text.splitlines() if ln.strip()]

    # ---- metadata ----
    out["comune"] = None
    out["zona"] = None
    out["periodo"] = None
    out["punto_prelievo"] = None
    for ln in lines[:15]:
        if out["comune"] is None:
            m = re.match(r"\s*Comune di\s+(.+)$", ln, re.IGNORECASE)
            if m:
                out["comune"] = _clean(m.group(1))
                continue
        if out["zona"] is None:
            m = re.match(r"\s*Approvvigionamento\s+(.+)$", ln, re.IGNORECASE)
            if m:
                out["zona"] = _clean(m.group(1))
                continue
        if out["punto_prelievo"] is None:
            m = re.match(r"\s*Punto di prelievo\s+(.+)$", ln, re.IGNORECASE)
            if m:
                out["punto_prelievo"] = _clean(m.group(1))
                continue
        if out["periodo"] is None:
            m = re.search(
                r"Periodo di monitoraggio[:\s]+(.+)$", ln, re.IGNORECASE
            )
            if m:
                out["periodo"] = _clean(m.group(1))
                continue

    # ---- parametri: ogni riga utile della tabella ha forma
    #      "<parametro> <unita> <limite> <valore>"
    # ma parametro e unita possono contenere spazi. Strategia: troviamo
    # l'inizio della tabella ("pH pH ..."), poi parse posizionale a destra.
    start_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^Prova\s+Unità", ln):
            start_idx = i + 1
            break
        if re.match(r"^pH\s+pH\b", ln, re.IGNORECASE):
            start_idx = i
            break
    if start_idx is None:
        out["summary"] = {
            "total_parameters": 0,
            "total_with_limit": 0,
            "exceedances": [],
            "status": "UNKNOWN",
        }
        return out

    # Token speciali che rappresentano "valore qualitativo" anziché numerico.
    QUAL_TOKENS = {
        "incolore", "inodore", "insapore", "conforme", "s.v.a.",
        "s.v.a.*", "n.d.", "n.d.**", "n.p.",
    }
    NOTE_PREFIXES = ("*", "**", "***")

    for ln in lines[start_idx:]:
        s = ln.strip()
        if not s or s.startswith(NOTE_PREFIXES):
            continue
        # Stop ai blocchi finali (note legenda).
        if re.match(r"^[*]+\s", s) or s.lower().startswith("legenda"):
            continue
        toks = s.split()
        if len(toks) < 3:
            continue
        # Strategia: l'ULTIMO token è il valore; il PENULTIMO è (parte del) limite
        # quando presente. Acqualatina ha 4 colonne fisse: prova/unita/limite/valore.
        # Quando il limite manca (es. "Temperatura ° C 25 15,4") la riga ha 4 token
        # comunque. Tutte le righe valide hanno almeno il valore.
        # Pattern token-finale "valore": numero, <numero, qualitativo, o range "0".
        last = toks[-1]
        is_value_like = (
            bool(re.match(r"^[<>]?\s*\d", last))
            or last.lower() in QUAL_TOKENS
            or last.lower() in {"0"}
        )
        if not is_value_like:
            continue
        valore = last
        # Ricostruzione naïve: ipotizziamo unità è 1-2 token, limite è 1-2 token.
        # Acqualatina usa unità tipo "mg/L", "µS/cm a 20°C", "ufc/100 ml".
        # Per semplicità: prendiamo l'intera riga e separiamo a posteriori i campi
        # via euristica: parametro = parole iniziali fino al primo token-unità,
        # ma è fragile. Manteniamo grezzo: parametro = primi token, limite="" ,
        # valore=last. Sufficiente per il calcolo di compliance qualitativo.
        head = " ".join(toks[:-1])
        # Heuristica: divide head in parametro+unita+limite se token contiene "/", "°C", "%"
        unit_idx = None
        for i, t in enumerate(toks[:-1]):
            if any(c in t for c in ("/", "°", "%")) or t.lower() in {
                "mg/l", "µg/l", "μg/l", "ufc/100", "ntu", "ph"
            }:
                unit_idx = i
                break
        if unit_idx is not None:
            parametro = " ".join(toks[:unit_idx]) if unit_idx > 0 else toks[0]
            # Se il parametro è vuoto (riga inizia con "pH pH ..."), usa il
            # primo token come parametro e considera l'unità da unit_idx+1.
            if not parametro:
                parametro = toks[0]
                unita_lim = toks[1:-1]
            else:
                unita_lim = toks[unit_idx:-1]
            # Unità può estendersi (es. "µS/cm a 20°C" -> 3 token). Cerchiamo
            # il primo token successivo che inizi con cifra o "<" o "n.": è il limite.
            # MA: scartiamo token che contengono "°" (sono continuazione di
            # unità, es. "20°C" in "µS/cm a 20°C").
            lim_start = None
            for j, t in enumerate(unita_lim):
                if j == 0:
                    continue
                if "°" in t:
                    continue
                if re.match(r"^([<>]?\s*\d|n\.[dp]\.|s\.v\.a)", t):
                    lim_start = j
                    break
            if lim_start is None:
                unita = " ".join(unita_lim)
                limite = ""
            else:
                unita = " ".join(unita_lim[:lim_start])
                limite = " ".join(unita_lim[lim_start:])
        else:
            parametro = head
            unita = ""
            limite = ""
        # Filtra righe non-parametro (es. footer)
        if not parametro or len(parametro) < 2:
            continue
        out["parameters"].append({
            "parametro": _clean(parametro),
            "unita": _clean(unita),
            "limite": _clean(limite),
            "valore": _clean(valore),
            "valore_num": _parse_number(valore),
            "limite_num": _parse_number(limite),
        })

    # ---- compliance summary (stesse regole del parser Acea) ----
    exceed: list[dict] = []
    total_with_limit = 0
    for p in out["parameters"]:
        v = p["valore_num"]
        lim_v = p["limite_num"]
        lim_raw = (p["limite"] or "").strip()
        val_raw = (p["valore"] or "").strip()
        if val_raw.lower() == "non conforme":
            exceed.append({"parametro": p["parametro"], "valore": p["valore"], "limite": p["limite"]})
            continue
        if val_raw.startswith("<"):
            if lim_v is not None:
                total_with_limit += 1
            continue
        if lim_v is None or v is None:
            continue
        # Salta limiti contenenti caratteri sospetti che indicano un parsing
        # ambiguo (es. "20°C 2500" -> il "limite" è in realtà unità+limite).
        if "°" in lim_raw or "<" in lim_raw or ">" in lim_raw:
            continue
        total_with_limit += 1
        if "cloro" in p["parametro"].lower() or "disinfettante" in p["parametro"].lower():
            continue
        if v > lim_v:
            exceed.append({"parametro": p["parametro"], "valore": p["valore"], "limite": p["limite"]})
    out["summary"] = {
        "total_parameters": len(out["parameters"]),
        "total_with_limit": total_with_limit,
        "exceedances": exceed,
        "status": "OK" if not exceed else "ATTENZIONE",
    }
    return out


def parse_pdf_aps(path: Path) -> dict:
    """
    Parser dedicato per i PDF "IMP*.pdf" del laboratorio Gruppo Maurizi
    (rapporti di prova per Acqua Pubblica Sabina S.p.A. — provincia di
    Rieti + sabina romana).

    Schema PDF (multi-pagina, 1-4 pagine):
      - Header testuale: "Punto di prelievo: COMUNE (RI|RM) - F.P. <descrizione>"
      - Tabella "PROVA / METODO / RISULTATO / Incertezza / LIMITI / LOQ / U.M. / Sede"
        ripartita su più pagine.

    Estrae **tutti** i parametri tabellari (non solo i 12 più comuni) usando
    ``pdfplumber.extract_tables()`` invece delle regex line-based che non
    riuscivano a catturare le righe wrappate su più linee.
    """
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {}}

    text_all = ""
    rows: list[list[str]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text_all += (page.extract_text() or "") + "\n"
            for tbl in page.extract_tables() or []:
                if not tbl or len(tbl) < 2:
                    continue
                header = [((c or "").strip()) for c in tbl[0]]
                # Solo le tabelle "RISULTATO DELLE PROVE".
                if not header or header[0].upper() != "PROVA":
                    continue
                for raw in tbl[1:]:
                    cells = [(c or "").replace("\n", " ").strip() for c in raw]
                    cells = [re.sub(r"\s+", " ", c) for c in cells]
                    if any(cells):
                        rows.append(cells)

    # ---- metadata (header testuale) ----
    m = re.search(
        r"Punto di prelievo:\s*([^()\-\n]+?)\s*\(\s*R[IM]\s*\)\s*"
        r"(?:-\s*(.*?))?\s*(?:-\s*Codice(?:\s+Comune)?:?\s*\d{6})?\s*\(\$\)",
        text_all,
        re.IGNORECASE,
    )
    if m:
        out["comune"] = _clean(m.group(1)).title()
        out["punto_prelievo"] = _clean(m.group(2) or "")
    else:
        out["comune"] = None
        out["punto_prelievo"] = None
    out["zona"] = out["punto_prelievo"]

    MESI = [
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ]
    m = re.search(r"Emissione rapporto:\s*(\d{2})/(\d{2})/(\d{4})", text_all)
    if m:
        d, mo, y = m.group(1), int(m.group(2)), m.group(3)
        out["periodo"] = f"{MESI[mo - 1]} {y}"
        out["data_emissione"] = f"{y}-{mo:02d}-{d}"
    else:
        out["periodo"] = None
        out["data_emissione"] = None

    # ---- parametri dalle tabelle ----
    # Schema riga atteso (8 colonne):
    #   0=PROVA  1=METODO  2=RISULTATO  3=Incertezza  4=LIMITI  5=LOQ  6=U.M.  7=Sede
    for r in rows:
        if len(r) < 7:
            continue
        prova = r[0]
        risultato = r[2] if len(r) > 2 else ""
        limiti = r[4] if len(r) > 4 else ""
        um = r[6] if len(r) > 6 else ""
        # Nome parametro: rimuovo marker laboratorio "(*)", "(&)", trailing dash/separator.
        param = re.sub(r"\s*\([*&]\)", "", prova).strip()
        param = re.sub(r"[-_=]{2,}\s*$", "", param).strip()
        param = re.sub(r"\s+", " ", param)
        if not param:
            continue
        # Salto righe vuote / placeholder
        if not risultato or risultato == "/":
            continue
        # Pulisco limite: strip riferimenti normativi "(D7)", "(D5)", "((\))" ecc.
        limite = re.sub(r"\s*\(D\d+\)\s*", "", limiti).strip()
        limite = re.sub(r"\s*\(\(.*?\)\)\s*", "", limite).strip()
        limite = re.sub(r"\s+", " ", limite)
        if limite in {"/", "-"}:
            limite = ""
        unita = re.sub(r"\s+", " ", (um or "").strip())
        if unita in {"/", "-"}:
            unita = ""
        out["parameters"].append({
            "parametro": param,
            "unita": unita,
            "limite": limite,
            "valore": risultato,
            "valore_num": _parse_number(risultato),
            "limite_num": _parse_number(limite),
        })

    # ---- compliance euristica ----
    # Parametri microbiologici che devono essere = 0.
    MICRO_ZERO = (
        "batteri coliformi", "escherichia coli",
        "pseudomonas aeruginosa", "enterococchi",
    )
    exceed: list[dict] = []
    for p in out["parameters"]:
        v_raw = p["valore"] or ""
        v = p["valore_num"]
        lim = p["limite_num"]
        label = p["parametro"].lower()
        # "<X" = sotto il limite di quantificazione → conforme
        if v_raw.lstrip().startswith("<"):
            continue
        # Microbiologici: anche un solo UFC → superamento
        if any(k in label for k in MICRO_ZERO):
            if v is not None and v > 0:
                exceed.append({
                    "parametro": p["parametro"],
                    "valore": p["valore"], "limite": p["limite"],
                })
            continue
        # pH: intervallo 6,5 — 9,5
        if label == "ph" or label.startswith("ph "):
            if v is not None and (v < 6.5 or v > 9.5):
                exceed.append({
                    "parametro": p["parametro"],
                    "valore": p["valore"], "limite": p["limite"],
                })
            continue
        # Limite numerico (max) → confronto diretto.
        if lim is not None and v is not None and v > lim:
            exceed.append({
                "parametro": p["parametro"],
                "valore": p["valore"], "limite": p["limite"],
            })

    out["summary"] = {
        "total_parameters": len(out["parameters"]),
        "total_with_limit": sum(1 for p in out["parameters"] if p["limite_num"] is not None),
        "exceedances": exceed,
        "status": "OK" if not exceed else "ATTENZIONE",
    }
    return out


def _worker(path_str: str) -> tuple[str, dict | str]:
    p = Path(path_str)
    try:
        # Dispatch in base al prefisso del nome file.
        if p.stem.startswith("acqualatina_"):
            return p.stem, parse_pdf_acqualatina(p)
        if p.stem.startswith("IMP"):
            return p.stem, parse_pdf_aps(p)
        return p.stem, parse_pdf(p)
    except Exception as e:  # pragma: no cover
        return p.stem, f"ERROR: {e!r}"


def main() -> int:
    # Costruisce mappa name -> provider dai GeoJSON disponibili.
    name_to_provider: dict[str, str] = {}
    for prov_id, gf in GEOJSON_FILES.items():
        if not gf.exists():
            continue
        try:
            data = json.loads(gf.read_text(encoding="utf-8"))
        except Exception:
            continue
        for feat in data.get("features", []):
            n = (feat.get("properties") or {}).get("name")
            if n:
                name_to_provider.setdefault(n, prov_id)
        print(f"[provider] {prov_id}: {len(data.get('features', []))} features")

    if not name_to_provider:
        print("Missing GeoJSON files. Run scrape.py first.")
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
                # Tagga il provider in base al GeoJSON di appartenenza.
                # I PDF "IMP*" sono SEMPRE Acqua Pubblica Sabina anche se non
                # rappresentativi (cioè non scelti come name di feature):
                # vengono raggruppati per comune in build_aps.py.
                if name.startswith("IMP"):
                    res["provider"] = "acqua_pubblica_sabina"
                else:
                    res["provider"] = name_to_provider.get(name, "acea_ato2")
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
