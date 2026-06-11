"""
Parser: estrae i parametri di qualità dell'acqua da ogni PDF
e produce backend/data/results.json.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
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
    "abruzzo": ROOT / "mappa-qualita-abruzzo.json",
    "campania": ROOT / "mappa-qualita-campania.json",
    "molise": ROOT / "mappa-qualita-molise.json",
    "puglia": ROOT / "mappa-qualita-puglia.json",
    "basilicata": ROOT / "mappa-qualita-basilicata.json",
    "toscana_nuoveacque": ROOT / "mappa-qualita-nuoveacque.json",
    "toscana_gaia": ROOT / "mappa-qualita-gaia.json",
    "toscana_publiacqua": ROOT / "mappa-qualita-publiacqua.json",
    "toscana_acque": ROOT / "mappa-qualita-acque.json",
    "toscana_asamap": ROOT / "mappa-qualita-asamap.json",
    "toscana_fiora": ROOT / "mappa-qualita-fiora.json",
    "marche_batch": ROOT / "mappa-qualita-marche-batch.json",
    "marche_multiservizi": ROOT / "mappa-qualita-marche-multiservizi.json",
    "marche_ciip": ROOT / "mappa-qualita-ciip.json",
    "sanmarino_aass": ROOT / "mappa-qualita-aass.json",
    "lazio_extra": ROOT / "mappa-qualita-lazio-extra.json",
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
    s = str(s)
    s = (s.replace("ľg/l", "µg/l")
           .replace("Âµg/l", "µg/l")
           .replace("痢/l", "µg/l")
           .replace("Â°", "°")
           .replace("unitÃ ", "unità"))
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


# ============================================================
# Parser ABRUZZO (CAM, Ruzzo, ACA, SASI)
# ============================================================

# Set di parametri tipici di un rapporto di prova di acqua potabile, con
# limiti di riferimento del D.Lgs. 18/2023 (Allegato I, parte B). Vengono
# usati come fallback quando il PDF non riporta esplicitamente i limiti
# (es. SASI, Ruzzo). Solo valori massimi; pH è gestito a parte.
_ABRUZZO_REF_LIMITS = {
    "nitrati": ("mg/l", 50.0),
    "nitriti": ("mg/l", 0.5),
    "ammonio": ("mg/l", 0.5),
    "cloruri": ("mg/l", 250.0),
    "solfati": ("mg/l", 250.0),
    "sodio": ("mg/l", 200.0),
    "fluoruri": ("mg/l", 1.5),
    "ferro": ("µg/l", 200.0),
    "alluminio": ("µg/l", 200.0),
    "manganese": ("µg/l", 50.0),
    "piombo": ("µg/l", 10.0),
    "nichel": ("µg/l", 20.0),
    "arsenico": ("µg/l", 10.0),
    "cadmio": ("µg/l", 5.0),
    "cromo": ("µg/l", 25.0),
    "rame": ("mg/l", 2.0),
    "boro": ("mg/l", 1.5),
    "conducibilità": ("µS/cm", 2500.0),
    "conduttività": ("µS/cm", 2500.0),
    "torbidità": ("NTU", 1.0),
    "antiparassitari totali": ("µg/l", 0.5),
    "idrocarburi policiclici aromatici": ("µg/l", 0.1),
    "trialometani totali": ("µg/l", 100.0),
    "uranio": ("µg/l", 30.0),
    "clorato": ("mg/l", 0.25),
    "clorito": ("mg/l", 0.25),
    "bromato": ("µg/l", 10.0),
}

_MICRO_PARAMS = (
    "escherichia coli", "batteri coliformi", "coliformi totali",
    "enterococchi", "pseudomonas aeruginosa", "clostridium",
    "microrganismi vitali",
)

# Parametri puramente operativi/descrittivi: presenti nei rapporti ma da
# escludere dal calcolo di conformità (non sono limiti sanitari del D.Lgs. 18/2023).
_SKIP_COMPLIANCE = (
    "cloro residuo", "disinfettante residuo", "cloro attivo libero",
    "temperatura", "potenziale redox", "carbonio inorganico",
    "carbonio totale", "residuo fisso",
)


def _abruzzo_compliance(out: dict) -> None:
    """Compila out['summary'] con regole comuni a tutti i parser Abruzzo."""
    # Punti di prelievo "pre clorazione" / "pre cloro" = monitoraggio sorgente,
    # NON acqua destinata al consumo. Non flaggare come ATTENZIONE: l'acqua
    # erogata viene poi trattata. Marca lo status come INFORMATIVO.
    zona_lower = (out.get("zona") or "").lower()
    is_pre_treatment = bool(re.search(
        r"pre\s*clor|pre\s+cloro|sorgente\s+pre|in\s+entrata|grezza|"
        r"-\s*pre\b|\bpre\s+Codice",
        zona_lower))
    exceed: list[dict] = []
    total_with_limit = 0
    for p in out["parameters"]:
        v = p.get("valore_num")
        lim = p.get("limite_num")
        val_raw = (p.get("valore") or "").strip()
        label = (p.get("parametro") or "").lower()
        if val_raw.startswith("<"):
            if lim is not None:
                total_with_limit += 1
            continue
        if any(k in label for k in _MICRO_PARAMS):
            total_with_limit += 1
            if v is not None and v > 0:
                exceed.append({"parametro": p["parametro"],
                               "valore": p["valore"], "limite": p["limite"] or "0"})
            continue
        if label == "ph" or label.startswith("ph "):
            if v is not None and (v < 6.5 or v > 9.5):
                exceed.append({"parametro": p["parametro"],
                               "valore": p["valore"], "limite": p["limite"] or "6,5–9,5"})
            total_with_limit += 1
            continue
        if "cloro" in label and "residuo" in label:
            continue  # parametro operativo, non sanitario
        if any(skip in label for skip in _SKIP_COMPLIANCE):
            continue  # parametri operativi/descrittivi
        if lim is None or v is None:
            continue
        total_with_limit += 1
        if v > lim:
            exceed.append({"parametro": p["parametro"],
                           "valore": p["valore"], "limite": p["limite"]})
    out["summary"] = {
        "total_parameters": len(out["parameters"]),
        "total_with_limit": total_with_limit,
        "exceedances": [] if is_pre_treatment else exceed,
        "status": ("INFORMATIVO" if is_pre_treatment
                   else ("OK" if not exceed else "ATTENZIONE")),
    }
    if is_pre_treatment:
        out["summary"]["note"] = (
            "Punto di prelievo pre-clorazione (acqua sorgente, non destinata "
            "direttamente al consumo). Il trattamento successivo riporta i "
            "valori entro i limiti di legge.")


def _abruzzo_lookup_limit(parametro: str) -> tuple[str, float] | None:
    pl = parametro.lower().strip()
    for key, (um, lim) in _ABRUZZO_REF_LIMITS.items():
        if key in pl:
            return um, lim
    return None


def parse_pdf_cam(path: Path) -> dict:
    """CAM S.p.A. (Marsica) — riepilogo annuale, 1 tabella per comune.

    Schema tabella:
      r0: [None, None, None, 'PUNTI DI CAMPIONAMENTO', ...]
      r1: ['PARAMETRO', 'Unità di Misura', 'Limite e valore guida', <punto1>, <punto2>, ...]
      r2..: dati. La colonna 'limite' ha forma '≥ 6,5 e ≤ 9,5' per pH, '50' per nitrati, ecc.

    Strategia: prendiamo il MASSIMO valore numerico fra tutti i punti di
    campionamento (worst-case) come rappresentativo del comune.
    """
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {},
                 "comune": None, "zona": None, "periodo": None}
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""
        tables = pdf.pages[0].extract_tables() or []
    # metadata
    m = re.search(r"COMUNE DI\s+([^\n]+)", text, re.IGNORECASE)
    if m:
        out["comune"] = _clean(m.group(1)).title()
    m = re.search(r"anno\s+(\d{4})", text, re.IGNORECASE)
    out["periodo"] = f"anno {m.group(1)}" if m else None
    out["zona"] = "Rete di distribuzione"

    if not tables:
        out["summary"] = {"total_parameters": 0, "total_with_limit": 0,
                          "exceedances": [], "status": "UNKNOWN"}
        return out
    tbl = tables[0]
    # individua riga header (prima riga con prima cella == 'PARAMETRO')
    header_idx = None
    for i, r in enumerate(tbl):
        if r and (r[0] or "").strip().upper() == "PARAMETRO":
            header_idx = i
            break
    if header_idx is None:
        out["summary"] = {"total_parameters": 0, "total_with_limit": 0,
                          "exceedances": [], "status": "UNKNOWN"}
        return out
    for row in tbl[header_idx + 1:]:
        if not row or not row[0]:
            continue
        parametro = _clean(row[0])
        if not parametro or len(parametro) < 2:
            continue
        unita = _clean(row[1] if len(row) > 1 else "")
        limite_raw = _clean(row[2] if len(row) > 2 else "")
        # estrai limite numerico massimo da stringhe tipo "≥ 6,5 e ≤ 9,5" → 9.5
        nums = re.findall(r"[<>≤≥]?\s*([0-9]+[.,]?[0-9]*)", limite_raw)
        lim_num = None
        if nums:
            try:
                lim_num = max(float(x.replace(",", ".")) for x in nums)
            except ValueError:
                lim_num = None
        # valori per ogni punto
        point_vals_raw = [_clean(c) for c in row[3:] if c and _clean(c) not in {"/", "-"}]
        if not point_vals_raw:
            continue
        # Scegli rappresentante: il MASSIMO valore numerico, oppure il primo
        # se nessuno è numerico (qualitativo: "Accettabile").
        nums_v = []
        for v in point_vals_raw:
            n = _parse_number(v)
            if n is not None:
                nums_v.append((n, v))
        if nums_v:
            chosen = max(nums_v, key=lambda x: x[0])
            valore = chosen[1]
            valore_num = chosen[0]
        else:
            valore = point_vals_raw[0]
            valore_num = None
        out["parameters"].append({
            "parametro": parametro,
            "unita": unita,
            "limite": limite_raw,
            "valore": valore,
            "valore_num": valore_num,
            "limite_num": lim_num,
        })
    _abruzzo_compliance(out)
    return out


# regex helper: numero italiano con virgola o punto, eventualmente con segno < >
_NUM_RE = re.compile(r"[<>]?\s*-?\d+(?:[.,]\d+)?")


# Sostituisce i codici CID prodotti da font senza mappa (frequenti nei referti
# AL Lab / Acquedotto Lucano): (cid:151)=µ, (cid:131)=°, (cid:147)=±.
_CID_SUBS = [("(cid:151)", "µ"), ("(cid:131)", "°"), ("(cid:147)", "±")]


def _extract_lab_text(path: Path) -> str:
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    t = "\n".join(parts)
    for bad, good in _CID_SUBS:
        t = t.replace(bad, good)
    return t


# Parametri canonici e loro alias come appaiono nei rapporti Abruzzo.
# (la chiave è il nome canonico, il valore è la lista di pattern testuali)
_ABRUZZO_PARAM_PATTERNS = [
    # Microbiologici (devono venire prima di pattern generici)
    ("Escherichia coli", [r"Escherichia\s+coli"]),
    ("Batteri coliformi", [r"Batteri\s+[Cc]oliformi", r"\bColiformi\s+totali\b"]),
    ("Enterococchi intestinali", [r"Enterococchi"]),
    ("Clostridium perfringens", [r"\bClostridium\s+perfri(?:n)?gens\b"]),
    ("Microrganismi vitali a 22°C", [r"Microrganismi\s+vitali\s+a?\s*22\s*°?\s*C?"]),
    ("Microrganismi vitali a 36°C", [r"Microrganismi\s+vitali\s+a?\s*36\s*°?\s*C?"]),
    ("Pseudomonas aeruginosa", [r"Pseudomonas\s+aeruginosa"]),
    # Parametri chimici principali
    ("pH", [r"\bpH\b", r"Concentrazione\s+ioni\s+idrogeno"]),
    ("Conducibilità", [r"\bConducibilit[àa]\b", r"\bConduttivit[àa]\b"]),
    ("Torbidità", [r"\bTorbidit[àa]\b"]),
    ("Cloro residuo", [r"\bCloro\s+residuo\b", r"\bCloro\s+attivo\s+libero\b",
                       r"Disinfettante\s+residuo"]),
    ("Nitrati", [r"\bNitrati\b", r"\bNitrato\b"]),
    ("Nitriti", [r"\bNitriti\b", r"\bNitrito\b"]),
    ("Ammonio", [r"\bAmmonio\b"]),
    ("Cloruri", [r"\bCloruri\b", r"\bCloruro\b"]),
    ("Solfati", [r"\bSolfati\b", r"\bSolfato\b"]),
    ("Sodio", [r"\bSodio\b"]),
    ("Fluoruri", [r"\bFluoruri\b", r"\bFluoruro\b"]),
    ("Ferro", [r"\bFerro\b"]),
    ("Manganese", [r"\bManganese\b"]),
    ("Alluminio", [r"\bAlluminio\b"]),
    ("Piombo", [r"\bPiombo\b"]),
    ("Nichel", [r"\bNichel\b"]),
    ("Arsenico", [r"\bArsenico\b"]),
    ("Cromo", [r"\bCromo(?:\s+totale)?\b"]),
    ("Rame", [r"\bRame\b"]),
    ("Boro", [r"\bBoro\b"]),
    ("Durezza", [r"\bDurezza\b"]),
    ("Calcio", [r"\bCalcio\b"]),
    ("Magnesio", [r"\bMagnesio\b"]),
    ("Potassio", [r"\bPotassio\b"]),
    ("Carbonio organico totale (TOC)", [r"Carbonio\s+[Oo]rganico\s+[Tt]otale", r"\bTOC\b"]),
    ("Carbonio inorganico (IC)", [r"Carbonio\s+inorganico", r"\bIC\b"]),
    ("Carbonio totale (TC)", [r"Carbonio\s+totale\b"]),
    ("Residuo fisso", [r"Residuo\s+fisso", r"Solidi\s+Totali\s+Disciolti", r"\bTDS\b"]),
    ("Potenziale Redox", [r"Potenziale\s+[Rr]edox"]),
    ("Temperatura", [r"\bTemperatura\s+(?:al\s+prelievo|aria|acqua)"]),
    ("Antiparassitari totali", [r"ANTIPARASSITARI\s+TOTALI", r"Antiparassitari\s+totali"]),
    ("Idrocarburi policiclici aromatici (IPA)", [r"IPA\s+totali", r"Idrocarburi\s+policiclici"]),
    ("Trialometani totali", [r"Trialometani"]),
    ("Bromato", [r"\bBromato\b"]),
    ("Clorato", [r"\bClorato\b"]),
    ("Clorito", [r"\bClorito\b"]),
    ("Uranio", [r"\bUranio\b"]),
    ("Cianuro", [r"\bCianuro\b"]),
    ("Selenio", [r"\bSelenio\b"]),
    ("Antimonio", [r"\bAntimonio\b"]),
    ("Mercurio", [r"\bMercurio\b"]),
    ("Vanadio", [r"\bVanadio\b"]),
]


def _abruzzo_extract_from_line(line: str) -> tuple[str, str, str] | None:
    """Da una riga testuale tipo:
        'Nitrati mg/l 1,5 50' (CAM/SASI)
        'pH (*) APAT CNR IRSA 2060 Man 29 2003 pH 8,04 6,5-9,5' (SASI)
        '--> -IPA totali " µg/l <0,002 ≤ 0.1 Calcolo' (ACA)
        'Nichel µg/l 20 1 1 1 /' (CAM multi-punto: già gestito da parser cam)
    estrae (valore, unita_hint, limite_hint) dal testo. Ritorna None se non
    si trova un numero plausibile."""
    # cattura tutti i numeri/<numeri
    nums = list(re.finditer(_NUM_RE, line))
    if not nums:
        return None
    # unità: cerchiamo token tipici mg/l, µg/l, NTU, µS/cm, °F, UFC/100ml, mV, pH
    um_match = re.search(
        r"\b(mg/l|µg/l|μg/l|ug/l|NTU|µS/cm|μS/cm|uS/cm|°F|UFC/100\s*ml|MPN/100\s*ml|UFC/100|MPN/100|mV|unit[àa]\s*pH|pH)\b",
        line, re.IGNORECASE)
    unita = um_match.group(1) if um_match else ""
    # range pH: "6,5-9,5" o "≥ 6,5 e ≤ 9,5"
    rng = re.search(r"([0-9]+[,\.][0-9]+)\s*[-–]\s*([0-9]+[,\.][0-9]+)", line)
    return ("", unita, rng.group(0) if rng else "")


def _parse_lab_report(path: Path, *, source: str) -> dict:
    """Parser line-based comune per Ruzzo / ACA / SASI (V3 multi-line aware).

    Strategia robusta:
      1. Per ogni riga, individua il parametro canonico (se presente).
      2. Per ogni occorrenza, compone una "riga logica" unendo la riga
         corrente + fino a 2 righe successive (fermandosi alla prossima
         occorrenza). Prepone anche la riga precedente se contiene un'unità
         di misura (caso ACA: "UFC/100\\nEscherichia coli 0 0 ...\\nml").
      3. Trova l'ultimo token di unità di misura nella riga composta; la
         coda dopo l'unità contiene i numeri (valore + LOQ/LOD + limiti).
      4. Filtra anni (1900-2099) e codici di metodo grandi (≥ 5000).
      5. valore = primo numero della coda; limite = ultimo numero (se > valore)
         oppure dal fallback `_ABRUZZO_REF_LIMITS`.
      6. Per parametri microbiologici il limite è sempre 0; valori "n.r."
         /"non rilevato"/"assente" sono trattati come 0.
    """
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {},
                 "comune": None, "zona": None, "periodo": None}
    text = _extract_lab_text(path)
    lines = [ln for ln in text.splitlines() if ln.strip()]

    # ---- metadata ----
    m = re.search(r"Comune(?:\s+di)?\s*[:\-]?\s*([A-Z][\wÀ-ÿ\s'’\-]+)", text)
    if m:
        cand = _clean(m.group(1))
        cand = re.split(r"\s+(?:Punto|Codice|Tipologia|Prodotto|Sorgente|Data|Rif)", cand)[0]
        out["comune"] = cand[:60].title()
    m = re.search(
        r"Data\s+(?:di\s+)?[Pp]relievo\s*[:\-]?\s*"
        r"(\d{1,2}[\-/](?:\d{1,2}|[a-zA-Z]{3})[\-/]\d{2,4})", text)
    if m:
        out["periodo"] = m.group(1)
    m = re.search(r"Punto(?:\s+di)?\s*[Pp]relievo\s*[:\-]?\s*([^\n]+)", text)
    if m:
        out["zona"] = _clean(m.group(1))[:80]

    # token unità di misura
    UNIT_RX = re.compile(
        r"(?:mg/l|µg/\s*l|μg/\s*l|ug/\s*l|NTU|µS/\s*cm|μS/\s*cm|uS/\s*cm|"
        r"microS/\s*cm|°F|UFC/100\s*ml|UFC/100|UFC/ml|MPN/100\s*ml|MPN/100|"
        r"mV|unit[àa]\s*pH|adimens\.?|°C)",
        re.IGNORECASE,
    )
    NUM_RX = re.compile(r"(?<![A-Za-z0-9.\-:/])([<>]?\s*-?\d+(?:[.,]\d+)?)(?![A-Za-z0-9])")
    SPECIAL_VAL = re.compile(
        r"\b(n\.?\s*r\.?|n\.?\s*d\.?|assente|negative|negativo|non\s+rilevat)\b",
        re.IGNORECASE,
    )

    # Mappa riga → primo canonico che vi compare (greedy per parametri lunghi prima)
    line_canon: dict[int, str] = {}
    for i, ln in enumerate(lines):
        if len(ln) > 400:
            continue
        for canon, patterns in _ABRUZZO_PARAM_PATTERNS:
            if any(re.search(p, ln, re.IGNORECASE) for p in patterns):
                line_canon[i] = canon
                break
    occ_set = set(line_canon.keys())

    seen_canon: set[str] = set()
    for line_idx in sorted(line_canon.keys()):
        canon = line_canon[line_idx]
        if canon in seen_canon:
            continue
        seen_canon.add(canon)
        is_ph = (canon == "pH")
        is_micro = any(k in canon.lower() for k in _MICRO_PARAMS)

        # Componi: riga corrente + fino a 2 righe successive (stop alla prossima occorrenza)
        cur = lines[line_idx]
        # Verifica se la riga corrente ha già unità + almeno un numero a destra
        # → in tal caso NON serve estendere (evita di "rubare" valori da righe
        # vicine quando il PDF mette ogni parametro su una riga distinta).
        cur_clean = cur
        for pat in patterns:
            cur_clean = re.sub(pat, " ", cur_clean, count=1, flags=re.IGNORECASE)
        cur_um = UNIT_RX.search(cur_clean)
        cur_has_value = bool(cur_um and NUM_RX.search(cur_clean[cur_um.end():]))
        cur_has_ph_value = is_ph and any(
            0 <= (_parse_number(nm.group(1).replace(" ", "")) or -99) <= 14
            for nm in NUM_RX.finditer(cur_clean))
        self_contained = cur_has_value or cur_has_ph_value

        parts = [cur]
        if not self_contained:
            for j in (1, 2):
                ni = line_idx + j
                if ni >= len(lines) or ni in occ_set:
                    break
                parts.append(lines[ni])
            # Prependi riga precedente se contiene un'unità (caso ACA col header
            # su riga separata) — SOLO se la riga corrente non ha già unità.
            if line_idx > 0 and (line_idx - 1) not in occ_set and not cur_um:
                prev = lines[line_idx - 1]
                if len(prev) < 80 and UNIT_RX.search(prev):
                    parts.insert(0, prev)
        composed = " ".join(parts)

        # Rimuovi il nome del parametro dalla riga composta, così "°C" dentro
        # "Microrganismi vitali a 22°C" non viene scambiato per unità.
        composed_clean = composed
        for pat in patterns:
            composed_clean = re.sub(pat, " ", composed_clean,
                                    count=1, flags=re.IGNORECASE)

        # Trova unità: PRIMA occorrenza nel composed_clean (l'unità precede
        # il valore nei rapporti di prova).
        ums = list(UNIT_RX.finditer(composed_clean))
        if ums:
            tail = composed_clean[ums[0].end():]
            unita = ums[0].group(0)
        else:
            if is_ph:
                # pH: usa la riga togliendo il nome parametro
                tail = re.sub(r"\bpH\b|Concentrazione\s+ioni\s+idrogeno", " ",
                              composed_clean, count=1, flags=re.IGNORECASE)
                unita = "pH"
            else:
                # Senza unità riconosciuta non possiamo estrarre con sicurezza
                continue

        # Tronca la coda al primo keyword di metodo (per evitare di catturare
        # codici di metodo come "2110", "9308" ecc. come valori/limiti).
        # Per pH NON troncare: i rapporti SASI mettono il valore DOPO il
        # codice metodo ("pH (*) APAT CNR IRSA 2060 Man 29 2003 pH 8,02 6,5-9,5").
        if not is_ph:
            method_kw = re.search(
                r"\b(APAT|UNI\s*EN|ISO\s+\d|CNR|IRSA|Rapporti\s+ISTISAN|"
                r"Met\.?\s+ISS|D\.?Lgs|Calcolo|Cromatografia|Astra|Sasi\s+Lab|"
                r"Potenziometria|Spettrofotometria|UNI\s+\d|EN\s+\d)\b",
                tail, re.IGNORECASE)
            if method_kw:
                tail = tail[:method_kw.start()]

        # Estrai numeri "puliti" dalla coda
        # Rimuovi footnote references "(1)", "(3)" che ACA pone in colonna Limiti
        tail = re.sub(r"\(\s*\d\s*\)", " ", tail)
        toks: list[tuple[str, float]] = []
        for nm in NUM_RX.finditer(tail):
            raw = nm.group(1).replace(" ", "")
            n = _parse_number(raw)
            if n is None:
                continue
            # Filtra anni 4-cifre 1900-2099
            if re.fullmatch(r"-?\d{4}", raw) and 1900 <= int(raw) <= 2099:
                continue
            # Filtra codici di metodo (interi ≥ 1000 senza decimali → quasi sempre
            # numero norma tipo "9308", "14189", "1622"). I limiti chimici reali
            # nei rapporti di prova sono < 3000 (conducibilità è 2500) e sempre
            # noti dalla tabella di riferimento.
            if re.fullmatch(r"-?\d{4,}", raw) and abs(n) >= 1000:
                continue
            # Filtra numeri seguiti da °C (temperatura di calibrazione/ricevimento,
            # es. "µS/cm a 20°C 199 ..." → scarta 20).
            after = tail[nm.end():nm.end() + 4]
            if re.match(r"\s*°\s*C", after):
                continue
            toks.append((raw, n))

        # Valori speciali per microbiologici (n.r. / assente / non rilevato)
        if not toks and is_micro:
            sv = SPECIAL_VAL.search(tail)
            if sv:
                toks = [("0", 0.0)]
        if not toks:
            continue

        # Per pH: filtra valori fuori range plausibile [0, 14]
        if is_ph:
            ph_toks = [(r, n) for r, n in toks if 0 <= n <= 14]
            if not ph_toks:
                continue
            toks = ph_toks

        valore_raw, valore_num = toks[0]

        # ----- limite -----
        ref = _abruzzo_lookup_limit(canon)
        lim_num: float | None = None
        limite_str = ""

        if is_micro:
            lim_num = 0.0
            limite_str = "0"
        elif is_ph:
            rng = re.search(
                r"([0-9][.,]?[0-9]*)\s*[-–]\s*([0-9][.,]?[0-9]*)", composed)
            if rng:
                limite_str = rng.group(0)
        elif ref:
            # Preferisci SEMPRE il limite ufficiale D.Lgs. 18/2023
            lim_num = ref[1]
            limite_str = str(ref[1]).replace(".", ",")
        elif len(toks) >= 2:
            # Solo se non c'è riferimento: ultimo numero come fallback
            last_raw, last_num = toks[-1]
            if (last_num is not None and last_num > 0
                    and last_num > (valore_num or 0)):
                limite_str = last_raw
                lim_num = last_num

        out["parameters"].append({
            "parametro": canon,
            "unita": _clean(unita),
            "limite": limite_str,
            "valore": valore_raw,
            "valore_num": valore_num,
            "limite_num": lim_num,
        })

    _abruzzo_compliance(out)
    out["_source"] = source
    return out


def parse_pdf_ruzzo(path: Path) -> dict:
    return _parse_lab_report(path, source="ruzzo")


def parse_pdf_aca(path: Path) -> dict:
    return _parse_lab_report(path, source="aca")


def parse_pdf_sasi(path: Path) -> dict:
    return _parse_lab_report(path, source="sasi")


def parse_pdf_gransasso(path: Path) -> dict:
    return _parse_lab_report(path, source="gransasso")


# Wrapper Campania: usano tutti il parser generico lab_report che funziona
# bene sui formati tabellari di ABC/Alto Calore/Gesesa/GORI/ITL/Nepta/Salerno.
def parse_pdf_campania(path: Path) -> dict:
    # Estrae il sotto-provider dal nome file:
    # campania_<provider>_<slug>.pdf  → source = "campania_<provider>"
    parts = path.stem.split("_", 2)
    src = "campania"
    if len(parts) >= 2 and parts[0] == "campania":
        src = f"campania_{parts[1]}"
    return _parse_lab_report(path, source=src)


# ======================================================================
# GRIM / Lab Ambiente e Sicurezza (Molise) — parser per layout tabellare
# "Prova | Risultato | Unità | Incertezza | Metodo | Classificazione |
# Limiti", in cui il VALORE precede l'unità. Molti rapporti di provincia
# sono scansioni senza layer testo → si usa OCR (RapidOCR) ricostruendo
# le righe della tabella dalle bounding box.
# ======================================================================
_OCR_ENGINE = None


def _get_ocr():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _cluster_rows(items: list[tuple[float, float, str]],
                  tol: float) -> list[str]:
    """items = [(y_center, x_center, text)] → righe ordinate per y, testo
    concatenato per x crescente. tol = tolleranza verticale (stessa riga)."""
    items = sorted(items, key=lambda t: t[0])
    rows: list[list[tuple[float, str]]] = []
    cur: list[tuple[float, str]] = []
    cur_y: float | None = None
    for cy, cx, txt in items:
        if cur_y is None or abs(cy - cur_y) <= tol:
            cur.append((cx, txt))
            cur_y = cy if cur_y is None else (cur_y + cy) / 2.0
        else:
            rows.append(cur)
            cur = [(cx, txt)]
            cur_y = cy
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        r.sort(key=lambda t: t[0])
        out.append(" ".join(t[1] for t in r))
    return out


def _grim_reconstruct_rows(path: Path) -> list[str]:
    """Ricostruisce le righe della tabella. Usa il layer testo (pdfplumber)
    se presente, altrimenti OCR della pagina renderizzata."""
    rows: list[str] = []
    import fitz  # PyMuPDF
    with pdfplumber.open(path) as pdf:
        plumber_pages = []
        for page in pdf.pages:
            words = page.extract_words() or []
            plumber_pages.append(words)
    doc = fitz.open(path)
    for i, page in enumerate(doc):
        words = plumber_pages[i] if i < len(plumber_pages) else []
        if words:
            items = [((w["top"] + w["bottom"]) / 2.0,
                      (w["x0"] + w["x1"]) / 2.0, w["text"]) for w in words]
            rows.extend(_cluster_rows(items, tol=3.0))
        else:
            import numpy as np
            pix = page.get_pixmap(dpi=300)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n)
            if pix.n == 4:
                img = img[:, :, :3]
            res, _ = _get_ocr()(img)
            if res:
                items = []
                for box, txt, _conf in res:
                    ys = [p[1] for p in box]
                    xs = [p[0] for p in box]
                    items.append((sum(ys) / 4.0, sum(xs) / 4.0, txt))
                rows.extend(_cluster_rows(items, tol=14.0))
    doc.close()
    return rows


# pattern allentati (gli OCR concatenano spesso le parole) — \s+ → \s*
_GRIM_PARAM_PATTERNS = [
    (canon, [p.replace(r"\s+", r"\s*") for p in pats])
    for canon, pats in _ABRUZZO_PARAM_PATTERNS
]
_GRIM_UNIT_RX = re.compile(
    r"(?:mg/\s*l|µg/\s*l|μg/\s*l|ug/\s*l|µg/\s*1|μg/\s*1|mg/\s*1|"
    r"NTU|µS/\s*cm|μS/\s*cm|uS/\s*cm|Hazen|°F|"
    r"UFC\s*/\s*\d*\s*m?l|MPN\s*/\s*\d*\s*m?l|mV|unit[àa]\s*di\s*pH|"
    r"unit[àa]\s*pH|adimens\.?)",
    re.IGNORECASE,
)
_GRIM_METHOD_RX = re.compile(
    r"(?i)\b(?:APAT|UNIENISO|UNIEN|UNIISO|UNI|ISO|CNR|IRSA|EN|Man|"
    r"Rapporti|ISTISAN|Met|Calcolo|Cromatografia|Spettro\w*|"
    r"Potenziom\w*)[\w:.\-/]*"
)
_GRIM_NUM_RX = re.compile(
    r"(?<![A-Za-z0-9.\-:/])([<>]?\s*-?\d+(?:[.,]\d+)?)(?![A-Za-z0-9])")


def _grim_unit_kind(u: str) -> str | None:
    """Restituisce 'mg' o 'ug' (microgrammi) dal testo unità, altrimenti None."""
    s = (u or "").lower().replace(" ", "")
    if "µg/" in s or "μg/" in s or "ug/" in s or "µg/1" in s or "μg/1" in s:
        return "ug"
    if "mg/" in s:
        return "mg"
    return None


def _parse_grim_rows(path: Path, *, source: str) -> dict:
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {},
                 "comune": None, "zona": None, "periodo": None}
    rows = _grim_reconstruct_rows(path)
    full = "\n".join(rows)

    # ---- metadata ----
    m = re.search(r"Comune\s+di\s+([A-Z][\wÀ-ÿ'’\-]+)", full)
    if m:
        out["comune"] = _clean(m.group(1)).title()
    m = re.search(r"Luogo\s+di\s+campionamento\s*:?\s*([^\n]+)", full,
                  re.IGNORECASE)
    if m:
        out["zona"] = _clean(m.group(1))[:80]
    m = re.search(r"Data\s+campionamento\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})",
                  full, re.IGNORECASE)
    if m:
        out["periodo"] = m.group(1)

    seen: set[str] = set()
    for row in rows:
        if len(row) > 300:
            continue
        canon = None
        pats = None
        for c, ps in _GRIM_PARAM_PATTERNS:
            if any(re.search(p, row, re.IGNORECASE) for p in ps):
                canon = c
                pats = ps
                break
        if not canon or canon in seen:
            continue

        is_micro = any(k in canon.lower() for k in _MICRO_PARAMS)
        is_ph = (canon == "pH")

        if is_ph:
            # Il pH va letto SOLO dalla riga analitica "… unità di pH …".
            # Le righe preliminari (es. "VALORI RILEVATI AL PRELIEVO PH 8.1
            # CL 0.3 …") contengono numeri di altri campi (cloro) che
            # falserebbero il valore. Il risultato è il numero subito prima
            # della dicitura "unità di pH".
            mph = re.search(r"unit[àa]\s*(?:di\s*)?pH", row, re.IGNORECASE)
            if not mph:
                continue  # riga non analitica → lascia che matchi una migliore
            head = row[:mph.start()]
            head = _GRIM_METHOD_RX.sub(" ", head)
            head = re.sub(r"[±]\s*\d+(?:[.,]\d+)?", " ", head)
            ph_toks: list[tuple[str, float]] = []
            for nm in _GRIM_NUM_RX.finditer(head):
                raw = nm.group(1).replace(" ", "")
                n = _parse_number(raw)
                if n is None:
                    continue
                # OCR: virgola persa (es. "73" = 7,3)
                if re.fullmatch(r"\d{2}", raw) and n > 14:
                    n = n / 10.0
                    raw = f"{n:g}".replace(".", ",")
                if 0 <= n <= 14:
                    ph_toks.append((raw, n))
            if not ph_toks:
                continue
            seen.add(canon)
            valore_raw, valore_num = ph_toks[-1]
            limite_str = ""
            rng = re.search(
                r"([0-9][.,]?[0-9]*)\s*[-–]\s*([0-9][.,]?[0-9]*)", row)
            if rng:
                limite_str = rng.group(0)
            out["parameters"].append({
                "parametro": canon, "unita": "unità di pH",
                "limite": limite_str, "valore": valore_raw,
                "valore_num": valore_num, "limite_num": None})
            continue

        # rimuovi il nome del parametro (così "22" in "...a 22°C" o "12" in
        # "(C12)" non vengano scambiati per valori).
        work = row
        for p in pats:
            work = re.sub(p, " ", work, count=1, flags=re.IGNORECASE)

        # Il layout è "Prova VALORE Unità Incertezza Metodo ... Limite":
        # il risultato è il numero IMMEDIATAMENTE prima dell'unità di misura.
        um = _GRIM_UNIT_RX.search(work)
        unita = _clean(um.group(0)) if um else ""
        head = work[:um.start()] if um else (work if is_ph else "")
        # togli incertezza e codici metodo eventualmente presenti nel "head"
        head = _GRIM_METHOD_RX.sub(" ", head)
        head = re.sub(r"[±]\s*\d+(?:[.,]\d+)?", " ", head)

        toks: list[tuple[str, float]] = []
        for nm in _GRIM_NUM_RX.finditer(head):
            raw = nm.group(1).replace(" ", "")
            n = _parse_number(raw)
            if n is None:
                continue
            if re.fullmatch(r"-?\d{4}", raw) and 1900 <= int(raw) <= 2099:
                continue
            after = head[nm.end():nm.end() + 4]
            if re.match(r"\s*°\s*C", after):
                continue
            toks.append((raw, n))

        if is_ph:
            toks = [(r, n) for r, n in toks if 0 <= n <= 14]

        if not toks:
            if is_micro:
                # micro senza colonia rilevata → assente
                seen.add(canon)
                out["parameters"].append({
                    "parametro": canon, "unita": "UFC",
                    "limite": "0", "valore": "0",
                    "valore_num": 0.0, "limite_num": 0.0})
            # non-micro senza numero valido prima dell'unità: salta
            # (evita di scambiare il valore-limite per il risultato).
            continue

        seen.add(canon)
        # il risultato è il numero più vicino all'unità (ultimo del head)
        valore_raw, valore_num = toks[-1]

        # limite (in unità coerente col valore per il confronto)
        lim_num = None
        limite_str = ""
        if is_micro:
            lim_num, limite_str = 0.0, "0"
        elif is_ph:
            rng = re.search(r"([0-9][.,]?[0-9]*)\s*[-–]\s*([0-9][.,]?[0-9]*)",
                            row)
            if rng:
                limite_str = rng.group(0)
        else:
            ref = _abruzzo_lookup_limit(canon)
            if ref:
                ref_um, ref_lim = ref
                lim_num = ref_lim
                rk, refk = _grim_unit_kind(unita), _grim_unit_kind(ref_um)
                # normalizza mg/l ↔ µg/l per un confronto corretto
                if rk and refk and rk != refk:
                    if refk == "mg" and rk == "ug":
                        lim_num = ref_lim * 1000.0
                    elif refk == "ug" and rk == "mg":
                        lim_num = ref_lim / 1000.0
                limite_str = (f"{lim_num:g}").replace(".", ",")

        out["parameters"].append({
            "parametro": canon,
            "unita": unita,
            "limite": limite_str,
            "valore": valore_raw,
            "valore_num": valore_num,
            "limite_num": lim_num,
        })

    _abruzzo_compliance(out)
    out["_source"] = source
    return out


# ---- Acquedotto Pugliese (AQP) — schede semestrali "Qualità dell'Acqua" ----
# Layout testuale pulito, una riga per parametro:
#   "<Parametro> <Valore> <Limite di legge> <Unità di misura> <Frequenza>"
# Il valore PRECEDE il limite che PRECEDE l'unità. "s.v.r." = senza valore di
# riferimento (nessun limite). Il PDF riporta già i limiti di legge.
_AQP_UNIT_CORE = re.compile(
    r"(?:µg/\s*l|μg/\s*l|mg/\s*l|µS/\s*cm|μS/\s*cm|NTU|"
    r"numero\s*/\s*\d*\s*ml|unit[àa]\s+di\s+pH|__)",
    re.IGNORECASE,
)
_AQP_SVR_RX = re.compile(r"s\.?\s*v\.?\s*r\.?", re.IGNORECASE)


def parse_pdf_puglia(path: Path) -> dict:
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {},
                 "comune": None, "zona": None, "periodo": None}
    lines: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            lines.extend(t.splitlines())
    full = "\n".join(lines)

    m = re.search(r"Comune\s*/\s*Zona\s*:\s*([^\n]+)", full, re.IGNORECASE)
    if m:
        z = _clean(m.group(1))
        out["comune"] = re.sub(r"\([A-Z]{2}\)\s*$", "", z).strip()
        out["zona"] = z
    m = re.search(r"Semestre\s*:\s*([^\n]+)", full, re.IGNORECASE)
    if m:
        out["periodo"] = _clean(m.group(1))

    seen: set[str] = set()
    for raw in lines:
        line = _clean(raw)
        if not line:
            continue
        um = None
        for mm in _AQP_UNIT_CORE.finditer(line):
            um = mm  # ultima occorrenza dell'unità nella riga
        if not um:
            continue
        unita = _clean(line[um.start():])
        # rimuovi la frequenza finale (intero) dall'unità
        unita = re.sub(r"\s+\d+\s*$", "", unita).strip()
        unita = re.sub(r"\s+", " ", unita)
        head = line[:um.start()].strip()
        if not head:
            continue

        # pH: il limite è un range ("‡6,5 e £9,5"); il valore è il 1° numero.
        if re.match(r"^pH\b", head, re.IGNORECASE):
            mv = re.search(r"^pH\s+([<>]?\d+(?:[.,]\d+)?)", head, re.IGNORECASE)
            if not mv or "pH" in seen:
                continue
            seen.add("pH")
            out["parameters"].append({
                "parametro": "pH", "unita": "Unità di pH",
                "limite": "6,5 - 9,5", "valore": mv.group(1),
                "valore_num": _parse_number(mv.group(1)), "limite_num": None})
            continue

        toks = head.split()
        if len(toks) < 3:
            continue
        # gli ultimi due token sono Valore e Limite; il resto è il parametro
        val_tok, lim_tok = toks[-2], toks[-1]
        parametro = _clean(" ".join(toks[:-2]))
        if not parametro or parametro.lower() in seen:
            continue

        def _is_val(t: str) -> bool:
            return bool(re.match(r"^[<>]?\d", t)) or bool(_AQP_SVR_RX.fullmatch(t))

        if not _is_val(val_tok) or not _is_val(lim_tok):
            continue

        seen.add(parametro.lower())
        valore_num = _parse_number(val_tok)
        if _AQP_SVR_RX.fullmatch(lim_tok):
            limite_str, limite_num = "", None
        else:
            limite_num = _parse_number(lim_tok)
            limite_str = lim_tok
        valore_str = "" if _AQP_SVR_RX.fullmatch(val_tok) else val_tok
        out["parameters"].append({
            "parametro": parametro, "unita": unita,
            "limite": limite_str, "valore": valore_str,
            "valore_num": valore_num, "limite_num": limite_num})

    _abruzzo_compliance(out)
    out["_source"] = "puglia_aqp"
    return out


def parse_pdf_basilicata(path: Path) -> dict:
    """Parser per i referti di Acquedotto Lucano S.p.A. (Basilicata).

    Due laboratori coinvolti:
    - Lab 1843 (AL interno): colonne «Nome prova | Metodo | Unità | Valore | LdR | Limiti».
      I font usano codici CID (corretti da _extract_lab_text): (cid:151)=µ, ecc.
    - Lab 0648 (SCA esterno): colonne «Parametri | Un.Misura | Risultati | U | Metodi | …».

    Il parser generico _parse_lab_report (Abruzzo) funziona su entrambi i layout
    perché in entrambi l'unità precede il valore. Qui aggiungiamo solo:
    1. La correzione CID (già in _extract_lab_text).
    2. Un'estrazione precisa del comune dall'intestazione «Comune: NOME».
    """
    out = _parse_lab_report(path, source="basilicata_al")
    # Il regex generico cattura troppo ("ABRIOLA\nLuogo di prelievo" → title-case errato).
    # Re-estraiamo il comune dalla prima riga «^Comune: NOME$».
    text = _extract_lab_text(path)
    m = re.search(r"^Comune\s*:\s*([A-ZÀÈÌÒÙÀ-ÿ][^\n]{0,50})", text, re.MULTILINE)
    if m:
        comune_raw = m.group(1).strip()
        # Togli eventuale testo sulla stessa riga oltre il comune (es. note)
        comune_raw = re.split(r"\s{3,}|\t", comune_raw)[0]
        out["comune"] = comune_raw.title()
    # Se il formato è SCA (niente riga «Comune:»), prova dalla descrizione campione.
    if not out.get("comune") or len(out.get("comune", "")) > 50:
        m2 = re.search(
            r"[Ss]erbatoio\s+[^\-\n]{0,60}[-–]\s*([A-ZÀÈÌÒÙ][a-zA-ZÀ-ÿ\s'']+?)"
            r"\s*(?:\([A-Z]{2}\))?\s*\n",
            text,
        )
        if m2:
            out["comune"] = m2.group(1).strip().title()
    out["_source"] = "basilicata_al"
    return out


def parse_pdf_molise(path: Path) -> dict:
    # molise_*_<slug>.pdf → rapporti di prova GRIM / Lab Ambiente e Sicurezza.
    # Layout "valore prima dell'unità"; le scansioni di provincia non hanno
    # layer testo → si ricostruisce la tabella via OCR.
    try:
        out = _parse_grim_rows(path, source="molise_acea")
    except Exception as exc:
        print(f"   ! GRIM parse fail {path.name}: {exc}")
        out = {"name": path.stem, "parameters": [], "sections": {},
               "comune": None, "zona": None, "periodo": None}
    # Fallback al parser generico se la ricostruzione non ha prodotto nulla.
    if not out.get("parameters"):
        out = _parse_lab_report(path, source="molise_acea")
    # Se proprio nessun parametro è estraibile, segnala documento informativo.
    if not out.get("parameters"):
        out.setdefault("summary", {})
        out["summary"].setdefault("total_parameters", 0)
        out["summary"].setdefault("total_with_limit", 0)
        out["summary"].setdefault("exceedances", [])
        out["summary"]["status"] = "INFORMATIVO"
        out["summary"]["note"] = (
            "Rapporto di prova fornito come documento scansionato: i singoli "
            "parametri non sono estraibili automaticamente. Il referto "
            "completo è consultabile e scaricabile dalla mappa.")
    return out



def parse_pdf_lazio_idrica(path: Path) -> dict:
    # lazio_idrica_<slug>.pdf → rapporti di prova Idrica (formato tabellare).
    out = _parse_lab_report(path, source="lazio_idrica_ardea")
    # Il PDF Idrica/Ardea è una scansione (nessun layer testo): pdfplumber
    # non estrae parametri. Fallback con i dati trascritti dal rapporto di
    # prova (campionamento 07/04/2025, D.Lgs 18/2023, tutti entro i limiti).
    if path.stem == "lazio_idrica_ardea" and not out.get("parameters"):
        out = _ardea_curated_report(path.stem)
    return out


def _ardea_curated_report(name: str) -> dict:
    """Dati trascritti dal rapporto di prova Idrica S.p.A. per Ardea (RM).

    Fonte: PDF scansionato 'analisi-delle-acque-04.25.pdf' (campionamento
    07/04/2025, norma D.Lgs n.18 del 23 febbraio 2023). Punto rappresentativo:
    Fontanella Via Lazio (centro storico). Tutti i valori entro i limiti.
    """
    def P(parametro, unita, valore, limite, valore_num=None, limite_num=None):
        return {"parametro": parametro, "unita": unita, "limite": limite,
                "valore": valore, "valore_num": valore_num,
                "limite_num": limite_num}

    params = [
        P("Carica batterica a 22 °C", "UFC/mL", "0", "S.V.A.", 0.0, None),
        P("Coliformi a 37 °C", "UFC/100 mL", "0", "0", 0.0, 0.0),
        P("Escherichia coli", "UFC/100 mL", "0", "0", 0.0, 0.0),
        P("Clostridium perfringens", "UFC/100 mL", "0", "0", 0.0, 0.0),
        P("Enterococchi", "UFC/100 mL", "0", "0", 0.0, 0.0),
        P("Colore", "-", "Incolore", "S.V.A."),
        P("Torbidità", "-", "Limpida", "S.V.A."),
        P("Odore", "-", "Inodore", "S.V.A."),
        P("Sapore", "-", "Insapore", "S.V.A."),
        P("pH", "unità pH", "6,5", "6,5 - 9,5", 6.5, None),
        P("Conduttività", "µS/cm a 20°C", "609", "2500", 609.0, 2500.0),
        P("Nitrito", "mg/L", "< 0,1", "0,50", 0.1, 0.5),
        P("Ammonio", "mg/L", "< 0,1", "0,50", 0.1, 0.5),
        P("Alluminio", "µg/L", "< 25", "200", 25.0, 200.0),
        P("Ferro", "µg/L", "< 20", "200", 20.0, 200.0),
        P("Arsenico", "µg/L", "< 3", "10", 3.0, 10.0),
        P("Disinfettante residuo", "mg/L Cl2", "0,20", "-", 0.2, None),
    ]
    total_with_limit = sum(1 for p in params if p["limite_num"] is not None)
    return {
        "name": name,
        "parameters": params,
        "sections": {},
        "comune": "Ardea",
        "zona": "Rete di distribuzione (fontanelle e serbatoio)",
        "periodo": "aprile 2025",
        "summary": {
            "total_parameters": len(params),
            "total_with_limit": total_with_limit,
            "exceedances": [],
            "status": "OK",
        },
        "_source": "lazio_idrica_ardea",
        "provider": "lazio_idrica_ardea",
    }


_NA_NUM = re.compile(r"[<>]?\d+(?:[.,]\d+)?")


def parse_pdf_nuoveacque(path: Path) -> dict:
    """Nuove Acque S.p.A. (Arezzo/Siena) — scheda «Qualità dell'acqua».

    Layout testuale pulito, una riga per parametro:
        ``<Parametro> <Valore> <Unità> <Limite>``
    Esempi:
        ``pH 7,96 tra 6,5 e 9,5``            (nessuna unità, limite = range)
        ``Durezza 22,11 °F Valore consigliato tra 15 e 50``
        ``Conducibilità 406,42 µScm-1 2500``
        ``Bicarbonati 208,16 mg/L HCO3 NL``  (unità multi-token, NL = nessun limite)
    """
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {},
                 "comune": None, "zona": None, "periodo": None}
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""
    lines = text.splitlines()

    m = re.search(r"Comune di\s+(.+)", text)
    if m:
        out["comune"] = _clean(m.group(1)).title()
    for ln in lines:
        if _clean(ln).upper().startswith("ACQUEDOTTO"):
            out["zona"] = _clean(ln)
            break
    m = re.search(r"dal\s+(\d{2}/\d{2}/\d{4})\s+al\s+(\d{2}/\d{2}/\d{4})", text)
    if m:
        out["periodo"] = f"dal {m.group(1)} al {m.group(2)}"

    started = False
    for ln in lines:
        s = _clean(ln)
        if not s:
            continue
        if s.startswith("Parametri") and "Valori medi" in s:
            started = True
            continue
        if not started:
            continue
        if s.startswith("I dati pubblicati") or s.startswith("Periodo di rifer"):
            break
        mnum = _NA_NUM.search(s)
        if not mnum:
            continue
        parametro = _clean(s[:mnum.start()])
        valore = mnum.group(0)
        rest = _clean(s[mnum.end():])
        if not parametro:
            continue

        unita = ""
        limite = ""
        limite_num = None
        if re.search(r"\btra\b", rest, re.IGNORECASE):
            # Limite a intervallo (pH, oppure "Valore consigliato tra X e Y").
            mr = re.search(
                r"(.*?)(?:Valore consigliato\s+)?\btra\s+([\d.,]+)\s+e\s+([\d.,]+)",
                rest, re.IGNORECASE)
            if mr:
                unita = _clean(mr.group(1))
                limite = f"{mr.group(2)} - {mr.group(3)}"
            else:
                limite = rest
        elif "NL" in rest:
            # NL = nessun limite normativo (parametro indicatore).
            unita = _clean(rest.replace("NL", ""))
        else:
            toks = rest.split()
            if toks and _NA_NUM.fullmatch(toks[-1]):
                limite = toks[-1]
                limite_num = _parse_number(limite)
                unita = _clean(" ".join(toks[:-1]))
            else:
                unita = rest

        if parametro.lower() == "ph" and not unita:
            unita = "Unità di pH"

        out["parameters"].append({
            "parametro": parametro,
            "unita": unita,
            "limite": limite,
            "valore": valore,
            "valore_num": _parse_number(valore),
            "limite_num": limite_num,
        })

    _abruzzo_compliance(out)
    out["_source"] = "toscana_nuoveacque"
    return out


def parse_pdf_gaia(path: Path) -> dict:
    """GAIA S.p.A. (Lucca/Massa-Carrara/Pistoia) — scheda «Qualità dell'acqua».

    PDF ricostruiti da ``scrape_gaia.py`` con tabella reportlab a 4 colonne:
        ``Parametri | Unità di Misura | Valore Medio | Limiti Normativi``
    Esempi di limite:
        ``> 6,5 e < 9,5``                   (pH, range → non vincolante)
        ``Valore consigliato 15 - 50``      (durezza, indicatore)
        ``Valore massimo consigliato 1500`` (residuo, indicatore)
        ``-``                               (nessun limite)
        ``0,50`` / ``2500`` / ``50``        (limite sanitario numerico)
    """
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {},
                 "comune": None, "zona": None, "periodo": None}
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""
        tables = pdf.pages[0].extract_tables() or []

    m = re.search(r"Comune:\s*(.+)", text)
    if m:
        out["comune"] = _clean(m.group(1)).title()
    m = re.search(r"Località:\s*(.+)", text)
    if m:
        out["zona"] = _clean(m.group(1)).title()
    m = re.search(r"Periodo di riferimento:\s*(.+)", text)
    if m:
        out["periodo"] = _clean(m.group(1))

    for tbl in tables:
        for row in tbl:
            if not row or len(row) < 4:
                continue
            parametro = _clean(row[0])
            if not parametro or parametro.lower() == "parametri":
                continue
            unita = _clean(row[1])
            valore = _clean(row[2])
            limite_raw = _clean(row[3])
            if not valore:
                continue

            limite_num = None
            low = limite_raw.lower()
            if not limite_raw or limite_raw == "-" or "consigliat" in low or " e " in low:
                # indicatore/range/non vincolante → nessun limite sanitario secco
                limite_num = None
            else:
                limite_num = _parse_number(limite_raw)

            out["parameters"].append({
                "parametro": parametro,
                "unita": unita,
                "limite": limite_raw,
                "valore": valore,
                "valore_num": _parse_number(valore),
                "limite_num": limite_num,
            })

    _abruzzo_compliance(out)
    out["_source"] = "toscana_gaia"
    return out


def _parse_toscana_limit(raw: str) -> float | None:
    low = (raw or "").lower()
    if not raw or raw in {"-", "/"} or "consigliat" in low:
        return None
    if "<=" in raw or ">=" in raw or " e " in low or "-" in raw:
        return None
    return _parse_number(raw)


def parse_pdf_publiacqua(path: Path) -> dict:
    """Publiacqua S.p.A. - schede qualita acqua ricostruite in PDF."""
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {},
                 "comune": None, "zona": None, "periodo": None}
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""
        tables = pdf.pages[0].extract_tables() or []

    meta: dict[str, str] = {}
    if tables:
        for row in tables[0]:
            if row and len(row) >= 2:
                meta[_clean(row[0]).lower()] = _clean(row[1])
    out["comune"] = meta.get("comune")
    out["zona"] = meta.get("indirizzo") or meta.get("codice") or name
    periodo = meta.get("periodo")
    if periodo:
        out["periodo"] = periodo.replace("Periodo di riferimento:", "").strip()
    else:
        m = re.search(r"Periodo di riferimento:\s*(.+)", text)
        if m:
            out["periodo"] = _clean(m.group(1))

    for tbl in tables[1:]:
        for row in tbl:
            if not row or len(row) < 4:
                continue
            parametro = _clean(row[0])
            if not parametro or parametro.lower() == "parametro":
                continue
            valore = _clean(row[1])
            limite_raw = _clean(row[2])
            unita = _clean(row[3])
            if not valore:
                continue
            out["parameters"].append({
                "parametro": parametro,
                "unita": unita,
                "limite": limite_raw,
                "valore": valore,
                "valore_num": _parse_number(valore),
                "limite_num": _parse_toscana_limit(limite_raw),
            })

    _abruzzo_compliance(out)
    out["_source"] = "toscana_publiacqua"
    return out


def parse_pdf_acque(path: Path) -> dict:
    """Acque S.p.A. - schede RIS di qualita acqua potabile."""
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {},
                 "comune": None, "zona": None, "periodo": None}
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""
        tables = pdf.pages[0].extract_tables() or []

    m = re.search(r"RIS:\s*(.+)", text)
    if m:
        out["zona"] = _clean(m.group(1))
    elif tables:
        for row in tables[0]:
            if row and len(row) >= 2 and _clean(row[0]).lower() == "codice":
                out["zona"] = _clean(row[1])
                break

    for tbl in tables:
        if not tbl:
            continue
        header = [_clean(c).lower() for c in (tbl[0] or [])]
        if len(header) < 5 or "parametro" not in header[0]:
            continue
        for row in tbl[1:]:
            if not row or len(row) < 5:
                continue
            parametro = _clean(row[0])
            if not parametro:
                continue
            unita = _clean(row[1])
            valore = _clean(row[2])
            limite_raw = _clean(row[3])
            decorrenza = _clean(row[4])
            if decorrenza and out["periodo"] is None:
                out["periodo"] = decorrenza
            if not valore:
                continue
            out["parameters"].append({
                "parametro": parametro,
                "unita": unita,
                "limite": limite_raw,
                "valore": valore,
                "valore_num": _parse_number(valore),
                "limite_num": _parse_toscana_limit(limite_raw),
            })

    _abruzzo_compliance(out)
    out["_source"] = "toscana_acque"
    return out


def parse_pdf_fiora(path: Path) -> dict:
    """Acquedotto del Fiora S.p.A. - schede qualita acqua."""
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {},
                 "comune": None, "zona": None, "periodo": None}
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""
        tables = pdf.pages[0].extract_tables() or []

    if tables:
        for row in tables[0]:
            if not row or len(row) < 2:
                continue
            key = _clean(row[0]).lower()
            val = _clean(row[1])
            if key == "comune":
                out["comune"] = val
            elif key == "zona":
                out["zona"] = val
            elif key == "periodo":
                out["periodo"] = val

    if not out["zona"]:
        m = re.search(r"Acquedotto del Fiora S\.p\.A\..*?\n(.+)", text)
        if m:
            out["zona"] = _clean(m.group(1))

    for tbl in tables:
        if not tbl:
            continue
        header = [_clean(c).lower() for c in (tbl[0] or [])]
        if len(header) < 4 or header[0] != "parametro":
            continue
        for row in tbl[1:]:
            if not row or len(row) < 3:
                continue
            parametro = _clean(row[0])
            limite_raw = _clean(row[1])
            valore = _clean(row[2])
            if not parametro or not valore:
                continue
            unita = ""
            m_unit = re.search(r"\(([^()]+)\)\s*$", valore)
            if m_unit:
                unita = _clean(m_unit.group(1))
                valore = _clean(valore[:m_unit.start()])
            if not unita:
                m_unit = re.search(r"/\s*([^()]+)\)", limite_raw)
                if m_unit:
                    unita = _clean(m_unit.group(1))
            out["parameters"].append({
                "parametro": parametro,
                "unita": unita,
                "limite": limite_raw,
                "valore": valore,
                "valore_num": _parse_number(valore),
                "limite_num": _parse_toscana_limit(limite_raw),
            })

    _abruzzo_compliance(out)
    out["_source"] = "toscana_fiora"
    return out


def parse_pdf_asamap(path: Path) -> dict:
    """ASA S.p.A. - etichette qualita acqua."""
    name = path.stem
    out: dict = {"name": name, "parameters": [], "sections": {},
                 "comune": None, "zona": None, "periodo": None}
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""

    lines = [_clean(line) for line in text.splitlines() if _clean(line)]
    for i, line in enumerate(lines):
        low = line.lower()
        if low.startswith("dati riferiti al periodo:"):
            out["periodo"] = _clean(line.split(":", 1)[1])
        elif "acquedotto di" in low:
            tail = _clean(re.split(r"acquedotto di", line, flags=re.I)[-1])
            if tail:
                out["zona"] = f"Acquedotto di {tail}".title()
            elif i + 1 < len(lines):
                out["zona"] = f"Acquedotto di {lines[i + 1]}".title()

    if not out["comune"]:
        parts = path.stem.split("_")
        if len(parts) >= 3 and parts[0] == "asamap":
            out["comune"] = " ".join(parts[2:]).title()
        elif len(parts) >= 2:
            out["comune"] = parts[1].replace("_", " ").title()
    if not out["zona"]:
        out["zona"] = name

    unit_re = r"(unità pH|microS/cm|µg/l|mg/l|°\s*F|°\s*C)"
    in_params = False
    for line in lines:
        if line.startswith("Ammonio "):
            in_params = True
        if not in_params:
            continue
        if line.startswith("Numero totale") or line.startswith("Tipo di disinfettante"):
            break
        m = re.match(rf"(.+?)\s+{unit_re}\s+(.+)$", line, re.I)
        if not m:
            continue
        parametro = _clean(m.group(1))
        unita = _clean(m.group(2))
        rest = _clean(m.group(3))
        parts = rest.split()
        if not parts:
            continue
        if len(parts) >= 2 and parts[0] in {"<", ">"}:
            valore = f"{parts[0]} {parts[1]}"
            limite_raw = _clean(" ".join(parts[2:]))
        elif " senza limite" in rest.lower():
            m_lim = re.search(r"\bsenza limite\b", rest, re.I)
            valore = _clean(rest[:m_lim.start()]) if m_lim else rest
            limite_raw = "senza limite"
        else:
            valore = parts[0]
            limite_raw = _clean(" ".join(parts[1:]))
        out["parameters"].append({
            "parametro": parametro,
            "unita": unita,
            "limite": limite_raw,
            "valore": valore,
            "valore_num": _parse_number(valore),
            "limite_num": _parse_toscana_limit(limite_raw),
        })

    _abruzzo_compliance(out)
    out["_source"] = "toscana_asamap"
    return out


_MARCHE_UNITS = (
    "MPN/100 ml", "ufc/100 ml", "ufc/ml", "unità di pH", "Unità pH",
    "µS/cm a 20°C", "µS cm¯¹ a 20°C", "µS/cm", "uS/cm a 20°C",
    "µs/cm", "mg/l NO3", "mg/l NO2", "mg/L", "mg/l", "µg/l", "ug/l",
    "°F", "NTU",
)


def _pdf_text(path: Path, max_pages: int | None = None) -> str:
    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        for page in pages:
            chunks.append(page.extract_text() or "")
    text = "\n".join(chunks)
    if len(text.strip()) < 20:
        ocr = _optional_ocr_text(path, max_pages=max_pages)
        if ocr.strip():
            return ocr
    return text


def _pdf_tables(path: Path, max_pages: int | None = None) -> list[list[list[str | None]]]:
    tables = []
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        for page in pages:
            tables.extend(page.extract_tables() or [])
    return tables


def _optional_ocr_text(path: Path, max_pages: int | None = None) -> str:
    try:
        import fitz  # type: ignore
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return ""
    chunks: list[str] = []
    doc = fitz.open(path)
    limit = len(doc) if max_pages is None else min(max_pages, len(doc))
    for i in range(limit):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        chunks.append(pytesseract.image_to_string(image, lang="ita+eng"))
    return "\n".join(chunks)


def _marche_periodo(text: str, stem: str) -> str | None:
    patterns = [
        r"Data prelievo:\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"Valori rilevati il\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"Valori rilevati dal\s*\d{1,2}/\d{1,2}/\d{2,4}\s+al\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"Data campionamento:\s*[¹\s]*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"Riferimento Rapporto di Prova[^\n]*?\sdel\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        r"\bANNO\s+(20\d{2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            val = _clean(m.group(1))
            if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2}", val):
                dd, mm, yy = val.split("/")
                return f"{int(dd):02d}/{int(mm):02d}/20{int(yy):02d}"
            return val
    m = re.search(r"(?<!\d)(\d{1,2})[._-](20\d{2})(?!\d)", stem)
    if m:
        return f"{int(m.group(1)):02d}/{m.group(2)}"
    m = re.search(r"\b(20\d{2})\b", stem)
    return m.group(1) if m else None


def _marche_base(path: Path, source: str) -> dict:
    return {
        "name": path.stem,
        "parameters": [],
        "sections": {},
        "comune": None,
        "zona": None,
        "periodo": None,
        "_source": source,
    }


def _marche_add_param(out: dict, parametro: str, unita: str, limite: str, valore: str) -> None:
    parametro = _clean(parametro)
    unita = _clean(unita).replace("µg/ l", "µg/l").replace("mg/ l", "mg/l").replace("m l", "ml")
    limite = _clean(limite)
    valore = _clean(valore)
    if not parametro or not valore:
        return
    low = parametro.lower()
    if low.startswith(("categoria", "parametro", "parametri", "prova", "metodo", "comune:")):
        return
    limite_num = _parse_marche_limit(limite)
    ref_limit = _marche_reference_limit(parametro)
    if _marche_no_individual_limit(parametro):
        limite_num = None
    elif ref_limit is not None and (
        limite_num is None
        or (limite_num > 0 and limite_num < ref_limit * 0.2)
    ):
        limite_num = ref_limit
        limite = f"{ref_limit:g}"
    out["parameters"].append({
        "parametro": parametro,
        "unita": unita,
        "limite": limite,
        "valore": valore,
        "valore_num": _parse_number(valore),
        "limite_num": limite_num,
    })


def _parse_marche_limit(raw: str) -> float | None:
    low = (raw or "").lower()
    if (
        not raw
        or raw in {"-", "/", "---"}
        or any(k in low for k in ("non previsto", "s.v.a", "senza variazioni", "accettabile"))
        or any(k in raw for k in ("÷", "≥", "≤"))
    ):
        return None
    return _parse_toscana_limit(raw)


def _marche_reference_limit(parametro: str) -> float | None:
    label = unicodedata.normalize("NFKD", parametro.lower())
    label = "".join(c for c in label if not unicodedata.combining(c))
    checks = [
        ("conducibilit", 2500.0), ("conduttivit", 2500.0),
        ("nitrati", 50.0), ("nitrato", 50.0),
        ("nitriti", 0.5), ("nitrito", 0.5),
        ("ammonio", 0.5), ("azoto ammoniacale", 0.5),
        ("cloruri", 250.0), ("cloruro", 250.0),
        ("solfati", 250.0), ("solfato", 250.0),
        ("sodio", 200.0), ("fluoruro", 1.5), ("fluoruri", 1.5),
        ("ferro", 200.0), ("manganese", 50.0), ("alluminio", 200.0),
        ("piombo", 10.0), ("nichel", 20.0), ("arsenico", 10.0),
        ("cadmio", 5.0), ("cromo", 25.0), ("rame", 2.0),
        ("boro", 1.5), ("antimonio", 10.0), ("mercurio", 1.0),
        ("selenio", 20.0), ("cianuro", 50.0), ("cianuri", 50.0),
        ("bromato", 10.0), ("clorato", 0.25), ("clorito", 0.25),
        ("antiparassitari", 0.5), ("trialometani", 30.0),
        ("uranio", 30.0),
    ]
    for needle, limit in checks:
        if needle in label:
            return limit
    return None


def _marche_no_individual_limit(parametro: str) -> bool:
    label = unicodedata.normalize("NFKD", parametro.lower())
    label = "".join(c for c in label if not unicodedata.combining(c))
    return any(k in label for k in (
        "durezza", "calcio", "magnesio", "potassio", "fosforo",
        "bicarbonato", "alcalinita", "residuo secco",
        "bromodiclorometano", "dibromoclorometano", "bromoformio", "cloroformio",
    ))


def _marche_finish(out: dict, note: str | None = None) -> dict:
    if out["parameters"]:
        _abruzzo_compliance(out)
    else:
        out["summary"] = {
            "total_parameters": 0,
            "total_with_limit": 0,
            "exceedances": [],
            "status": "INFORMATIVO",
        }
    if note:
        out["summary"]["note"] = note
    return out


def _value_and_limit_from_rest(rest: str) -> tuple[str, str]:
    rest = _clean(rest)
    if not rest:
        return "", ""
    low = rest.lower()
    if low.startswith("accettabile"):
        return "accettabile", "Accettabile per i consumatori e senza variazioni anomale"
    if low.startswith("non previsto"):
        return "non previsto", ""
    if rest.startswith("<"):
        m = re.match(r"(<\s*(?:LQ|[0-9]+(?:[.,][0-9]+)?))\s*(.*)$", rest, re.I)
        return (_clean(m.group(1)), _clean(m.group(2))) if m else (rest, "")
    first = rest.split()[0]
    tail = _clean(rest[len(first):])
    if tail.lower().startswith("tra"):
        m = re.match(r"(tra\s+[0-9.,]+\s+e\s+[0-9.,]+)", tail, re.I)
        return first, _clean(m.group(1)) if m else tail
    if tail.lower().startswith("senza variazioni"):
        return first, "Senza variazioni anomale"
    if tail.lower().startswith("non previsto"):
        return first, "non previsto"
    if tail:
        m = re.match(r"([<>≤≥=]*\s*[0-9]+(?:[.,][0-9]+)?(?:\([^)]+\))?)", tail)
        if m:
            return first, _clean(m.group(1))
    return first, tail


def _parse_marche_text_lines(out: dict, text: str) -> None:
    unit_re = "|".join(re.escape(u) for u in sorted(_MARCHE_UNITS, key=len, reverse=True))
    for raw in text.splitlines():
        line = _clean(raw)
        if not line or line.lower().startswith(("parametro ", "unità ", "misura ")):
            continue
        m_desc = re.match(r"^(Colore|Odore|Sapore)\s+(accettabile|inodore|insapore|incolore)\b", line, re.I)
        if m_desc:
            _marche_add_param(
                out, m_desc.group(1), "", "Accettabile per i consumatori e senza variazioni anomale", m_desc.group(2)
            )
            continue
        m = re.match(rf"(.+?)\s+({unit_re})\s+(.+)$", line, re.I)
        if not m:
            continue
        parametro = m.group(1)
        unita = m.group(2)
        valore, limite = _value_and_limit_from_rest(m.group(3))
        _marche_add_param(out, parametro, unita, limite, valore)


def parse_pdf_marche_apmgroup(path: Path) -> dict:
    out = _marche_base(path, "marche_apmgroup")
    text = _pdf_text(path, max_pages=1)
    out["periodo"] = _marche_periodo(text, path.stem)
    m = re.search(r"COMUNE DI\s+([^\n]+)", text, re.I)
    out["comune"] = _clean(m.group(1)).title() if m else None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        out["zona"] = _clean(lines[1])

    for table in _pdf_tables(path):
        header_idx = None
        for i, row in enumerate(table):
            joined = " ".join(_clean(c) for c in row if c)
            if "Parametri" in joined and "Limiti" in joined:
                header_idx = i
                break
        if header_idx is None:
            continue
        for row in table[header_idx + 1:]:
            if not row or len(row) < 5:
                continue
            parametro = _clean(row[0])
            unita = _clean(row[1])
            limite = _clean(row[3]) or _clean(row[2])
            values = [_clean(c) for c in row[4:] if _clean(c)]
            if not values:
                continue
            _marche_add_param(out, parametro, unita, limite, values[-1])
    return _marche_finish(out)


def parse_pdf_marche_multiservizi(path: Path) -> dict:
    out = _marche_base(path, "marche_multiservizi")
    text = _pdf_text(path)
    out["periodo"] = _marche_periodo(text, path.stem)
    m = re.search(r"Acquedotto\s+(.+?)\s+Data prelievo", text, re.I)
    out["comune"] = _clean(m.group(1)) if m else None
    m = re.search(r"Punto di prelievo:\s*([^\n]+)", text, re.I)
    out["zona"] = _clean(m.group(1)) if m else out["comune"]
    _parse_marche_text_lines(out, text)
    return _marche_finish(out)


def parse_pdf_marche_vivaservizi(path: Path) -> dict:
    out = _marche_base(path, "marche_vivaservizi")
    text = _pdf_text(path)
    out["periodo"] = _marche_periodo(text, path.stem)
    m = re.search(r"Comune:\s*([^\n-]+)(?:-\s*Punto di prelievo:\s*([^\n]+))?", text, re.I)
    if m:
        out["comune"] = _clean(m.group(1))
        out["zona"] = _clean(m.group(2)) if m.group(2) else out["comune"]
    elif path.stem.startswith("marche_vivaservizi_"):
        out["zona"] = path.stem.replace("marche_vivaservizi_", "").replace("_", " ").title()
    for table in _pdf_tables(path):
        for row in table:
            if not row or len(row) < 5:
                continue
            parametro = _clean(row[1] if len(row) > 1 else "")
            unita = _clean(row[2] if len(row) > 2 else "")
            limite = _clean(row[3] if len(row) > 3 else "")
            valore = _clean("".join(_clean(c) for c in row[4:] if _clean(c)))
            _marche_add_param(out, parametro, unita, limite, valore)
    return _marche_finish(out)


def parse_pdf_marche_atac(path: Path) -> dict:
    out = _marche_base(path, "marche_atac_civitanova")
    text = _pdf_text(path)
    out["periodo"] = _marche_periodo(text, path.stem)
    m = re.search(r"COMUNE DI\s+([^\n]+)", text, re.I)
    out["comune"] = _clean(m.group(1)).title() if m else "Civitanova Marche"
    m = re.search(r"INDIRIZZO DI FORNITURA:\s*[“\"]([^”\"]+)", text, re.I)
    out["zona"] = _clean(m.group(1)) if m else None
    for table in _pdf_tables(path):
        for row in table:
            if not row or len(row) < 5:
                continue
            parametro = _clean(row[0])
            if not parametro or parametro.lower() == "parametri":
                continue
            _marche_add_param(out, parametro, _clean(row[1]), _clean(row[4]), _clean(row[3]))
    return _marche_finish(out)


def _assem_result_line(line: str) -> tuple[str, str, str] | None:
    line = re.sub(r"[①②③④⑤⑥⑦⑧⑨#]", " ", _clean(line))
    m = re.match(r"(?P<value><\s*LQ|<\s*[0-9.,]+|[0-9.,]+|NP|inodore|insapore|incolore)\s+(?P<rest>.+)$", line, re.I)
    if not m:
        return None
    value = _clean(m.group("value"))
    rest = _clean(m.group("rest"))
    unit_match = None
    for unit_candidate in sorted(_MARCHE_UNITS, key=len, reverse=True):
        idx = rest.lower().find(unit_candidate.lower())
        if idx >= 0:
            unit_match = (unit_candidate, idx, idx + len(unit_candidate))
            break
    if not unit_match:
        if "S.V.A" in rest.upper():
            return value, "", "S.V.A."
        return value, "", rest
    unit = _clean(unit_match[0])
    tail = _clean(rest[unit_match[2]:])
    if "S.V.A" in tail.upper():
        limit = "S.V.A."
    else:
        m_lim = re.search(r"([0-9]+(?:[.,][0-9]+)?)", tail)
        limit = m_lim.group(1) if m_lim else ""
    return value, unit, limit


def parse_pdf_marche_assemspa(path: Path) -> dict:
    out = _marche_base(path, "marche_assemspa")
    text = _pdf_text(path)
    out["periodo"] = _marche_periodo(text, path.stem)
    m = re.search(r"Luogo di campionamento:.*?Comune di\s+(.+?)(?:\s+-|\n)", text, re.I | re.S)
    out["comune"] = _clean(m.group(1)) if m else None
    m = re.search(r"Descrizione:\s*[¹\s]*(.+)", text, re.I)
    out["zona"] = _clean(m.group(1)) if m else None
    lines = [_clean(ln) for ln in text.splitlines() if _clean(ln)]
    skip = ("UNI ", "APAT ", "Legenda", "Campionamento", "Cliente.", "Il presente", "Analisi Control")
    start_idx = 0
    for idx, line in enumerate(lines):
        if line.startswith("Prova Risultato") or line == "Metodo A B C Rif.":
            start_idx = idx + 1
            break
    for i, line in enumerate(lines[start_idx:], start=start_idx):
        if line.startswith(skip) or line in {"ANALISI", "Metodo A B C Rif."}:
            continue
        if line.startswith("pH ") or line.startswith("pH(") or "concentrazione in ioni idrogeno" in line:
            if i + 1 < len(lines):
                m_value = re.search(r"[0-9]+(?:[.,][0-9]+)?", lines[i + 1])
                if m_value:
                    _marche_add_param(out, "pH", "unità di pH", ">=6,5 e <=9,5", m_value.group(0))
            continue
        if i + 1 >= len(lines):
            continue
        parsed = _assem_result_line(lines[i + 1])
        if parsed:
            value, unit, limit = parsed
            _marche_add_param(out, line, unit, limit, value)
    return _marche_finish(out)


def parse_pdf_marche_asteaspa(path: Path) -> dict:
    out = _marche_base(path, "marche_asteaspa")
    text = _pdf_text(path)
    out["periodo"] = _marche_periodo(text, path.stem)
    m = re.search(r"Comune:\s*([^\n(]+)(?:\(([^)]+)\))?", text, re.I)
    if m:
        out["comune"] = _clean(m.group(1))
        out["zona"] = _clean(m.group(2)) if m.group(2) else out["comune"]
    for table in _pdf_tables(path):
        for row in table:
            if not row or len(row) < 4:
                continue
            _marche_add_param(out, _clean(row[0]), _clean(row[1]), _clean(row[2]), _clean(row[3]))
    if not out["parameters"]:
        # Se OCR opzionale produce testo tabellare, prova almeno il parser lineare.
        _parse_marche_text_lines(out, text)
    if not out["zona"]:
        out["zona"] = path.stem.replace("marche_asteaspa_", "").replace("_", " ").title()
    return _marche_finish(
        out,
        None if out["parameters"] else "PDF scansionato/non testuale: OCR non disponibile nell'ambiente corrente.",
    )


def parse_pdf_ciip(path: Path) -> dict:
    """CIIP S.p.A. (ATO 5 Marche Sud) — referti per utenza generati da
    servizi.ciip.it. Tabella: Descrizione / Valore / Unità / Limiti."""
    out = _marche_base(path, "marche_ciip")
    text = _pdf_text(path, max_pages=1)
    out["periodo"] = _marche_periodo(text, path.stem)
    m = re.search(r"comune:\s*([^/\n]+)", text, re.I)
    out["comune"] = _clean(m.group(1)).title() if m else None
    m_via = re.search(r"via:\s*([^/\n]+)", text, re.I)
    m_civ = re.search(r"civico:\s*([^/\n]+)", text, re.I)
    if m_via:
        zona = _clean(m_via.group(1)).title()
        civ = _clean(m_civ.group(1)) if m_civ else ""
        if civ and civ.upper() not in {"", "0", "0000", "SNC"}:
            zona = f"{zona}, {civ}"
        out["zona"] = zona
    for table in _pdf_tables(path):
        for row in table:
            if not row or len(row) < 3:
                continue
            desc = _clean(row[0])
            if not desc or desc.lower().startswith("descrizione"):
                continue
            valore = _clean(row[1])
            unita = _clean(row[2]) if len(row) > 2 else ""
            limite = _clean(row[3]) if len(row) > 3 else ""
            _marche_add_param(out, desc, unita, limite, valore)
    return _marche_finish(out)


_AASS_VALUE_RE = re.compile(r"^([<>]?\s*\d+(?:[.,]\d+)?)")


def _aass_clean_value(cell: str) -> str:
    """Rimuove i marcatori di nota a piè pagina ('< 1 3' → '< 1')."""
    m = _AASS_VALUE_RE.match(_clean(cell))
    return _clean(m.group(1)) if m else _clean(cell)


def parse_pdf_aass(path: Path) -> dict:
    """AASS San Marino — valori medi semestrali per castello. La prima pagina
    è l'anno più recente; colonne: Parametro / U.d.M. / sem.1 / sem.2 / limite."""
    out = _marche_base(path, "sanmarino_aass")
    text = _pdf_text(path, max_pages=1)
    m = re.search(r"CASTELLO DI\s+([^\n]+)", text, re.I)
    castello = _clean(m.group(1)).title() if m else path.stem.replace("_", " ")
    out["comune"] = castello
    out["zona"] = f"Castello di {castello}"
    dates = re.findall(r"al\s+(\d{1,2})/(\d{1,2})/(20\d{2})", text)
    if dates:
        _, mm, yy = dates[-1]
        out["periodo"] = f"{int(mm):02d}/{yy}"
    m = re.search(r"Serbatoi di influenza:\s*([^\n]+)", text, re.I)
    if m:
        out["sections"]["Serbatoi di influenza"] = _clean(m.group(1))
    tables = _pdf_tables(path, max_pages=1)
    for table in tables:
        header_seen = False
        for row in table:
            if not row or len(row) < 5:
                continue
            if _clean(row[0]).lower() == "parametro":
                header_seen = True
                continue
            if not header_seen:
                continue
            parametro = _clean(row[0])
            unita = _clean(row[1])
            # Valore più recente: secondo semestre; fallback sul primo.
            valore = _aass_clean_value(row[3] or "") or _aass_clean_value(row[2] or "")
            limite = re.sub(r"\s+\d$", "", _clean(row[4]))  # toglie nota a piè pagina
            _marche_add_param(out, parametro, unita, limite, valore)
    note = "Valori medi semestrali pubblicati da AASS (Repubblica di San Marino)."
    return _marche_finish(out, note)


def _worker(path_str: str) -> tuple[str, dict | str]:
    p = Path(path_str)
    try:
        # Dispatch in base al prefisso del nome file.
        if p.stem.startswith("abruzzo_cam_"):
            return p.stem, parse_pdf_cam(p)
        if p.stem.startswith("abruzzo_ruzzo_"):
            return p.stem, parse_pdf_ruzzo(p)
        if p.stem.startswith("abruzzo_aca_"):
            return p.stem, parse_pdf_aca(p)
        if p.stem.startswith("abruzzo_sasi_"):
            return p.stem, parse_pdf_sasi(p)
        if p.stem.startswith("abruzzo_gransasso_"):
            return p.stem, parse_pdf_gransasso(p)
        if p.stem.startswith("campania_"):
            return p.stem, parse_pdf_campania(p)
        if p.stem.startswith("molise_"):
            return p.stem, parse_pdf_molise(p)
        if p.stem.startswith("puglia_aqp_"):
            return p.stem, parse_pdf_puglia(p)
        if p.stem.startswith("basilicata_al_"):
            return p.stem, parse_pdf_basilicata(p)
        if p.stem.startswith("nuoveacque_"):
            return p.stem, parse_pdf_nuoveacque(p)
        if p.stem.startswith("gaia_"):
            return p.stem, parse_pdf_gaia(p)
        if p.stem.startswith("publiacqua_"):
            return p.stem, parse_pdf_publiacqua(p)
        if p.stem.startswith("acque_"):
            return p.stem, parse_pdf_acque(p)
        if p.stem.startswith("fiora_"):
            return p.stem, parse_pdf_fiora(p)
        if p.stem.startswith("asamap_"):
            return p.stem, parse_pdf_asamap(p)
        if p.stem.startswith("marche_apmgroup_"):
            return p.stem, parse_pdf_marche_apmgroup(p)
        if p.stem.startswith("marche_assemspa_"):
            return p.stem, parse_pdf_marche_assemspa(p)
        if p.stem.startswith("marche_asteaspa_"):
            return p.stem, parse_pdf_marche_asteaspa(p)
        if p.stem.startswith("marche_atac_civitanova_"):
            return p.stem, parse_pdf_marche_atac(p)
        if p.stem.startswith("marche_vivaservizi_"):
            return p.stem, parse_pdf_marche_vivaservizi(p)
        if p.stem.startswith("marche_multiservizi_"):
            return p.stem, parse_pdf_marche_multiservizi(p)
        if p.stem.startswith("marche_ciip_"):
            return p.stem, parse_pdf_ciip(p)
        if p.stem.startswith("sanmarino_aass_"):
            return p.stem, parse_pdf_aass(p)
        if p.stem.startswith("lazio_idrica_"):
            return p.stem, parse_pdf_lazio_idrica(p)
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
            props = feat.get("properties") or {}
            n = props.get("name")
            if n:
                # Se la feature porta un suo `provider` (sub-tipo, es.
                # abruzzo_cam / abruzzo_ruzzo), preferiscilo al provider id
                # del file GeoJSON contenitore.
                feat_prov = props.get("provider") or prov_id
                name_to_provider.setdefault(n, feat_prov)
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
