"""
Costruisce nomi display ricchi e human-friendly per ciascuna zona Acea Ato 2.

Problema: i nomi grezzi sono come 'roma_e_fiumicino_zona_5_acqua_marcia' o
'agosta_zona_2_madonna_della_pace', e il campo `zona` proveniente dal PDF è
ad es. '5 ACQUA MARCIA' — informazioni che da sole non fanno capire all'utente
di che area geografica si tratti, specie per Roma dove tutte le 10 zone
condividono lo stesso comune "Roma e Fiumicino".

Output per ogni zona:
  display_name : titolo principale ("Monteverde Vecchio", "Madonna della Pace")
  area         : sottotitolo con il contesto geografico ("Roma · Settore Ovest")
  aqueduct     : acquedotto fornitore identificato (es. "Peschiera-Capore")
  aqueduct_hint: nota didascalica sull'acquedotto (storia / dove sorge)
  zone_num     : numero della zona (string)
  icon         : emoji rappresentativa
  badges       : lista di etichette pillole (es. ["storico", "litorale"])
  search_tokens: stringa con tutti i sinonimi/quartieri per la ricerca full-text
"""
from __future__ import annotations
import re
from typing import Any


# ---------- mappatura curata 10 zone Roma+Fiumicino ----------
# Basata sui descrittori dei PDF Acea + conoscenza degli acquedotti che
# alimentano i diversi quadranti della città.
ROMA_ZONES: dict[str, dict[str, Any]] = {
    "roma_e_fiumicino_zona_1_monteverde_vecchio": {
        "display_name": "Monteverde Vecchio",
        "area": "Roma · Settore Ovest (Gianicolense)",
        "aqueduct": "Peschiera-Capore",
        "icon": "🏛️",
        "badges": ["quartiere storico", "Roma ovest"],
        "search_tokens": "monteverde vecchio gianicolense trastevere portuense roma ovest",
    },
    "roma_e_fiumicino_zona_2_peschiera_capore_+_vigne_nuove": {
        "display_name": "Vigne Nuove e Roma Nord",
        "area": "Roma · Settore Nord (Bufalotta, Talenti)",
        "aqueduct": "Peschiera-Capore",
        "icon": "🌳",
        "badges": ["Roma nord"],
        "search_tokens": "vigne nuove bufalotta talenti fidene cassia flaminia roma nord",
    },
    "roma_e_fiumicino_zona_3_peschiera_capore": {
        "display_name": "Roma Centrale (rete Peschiera-Capore)",
        "area": "Centro storico, Prati, Parioli, Trieste",
        "aqueduct": "Peschiera-Capore",
        "icon": "🏟️",
        "badges": ["centro città"],
        "search_tokens": "centro storico prati parioli trieste flaminio salario nomentano peschiera capore",
    },
    "roma_e_fiumicino_zona_4_nuovo_vergine_prevalente": {
        "display_name": "Centro Antico (acquedotto Vergine)",
        "area": "Trevi, Pantheon, Campo Marzio, Quirinale",
        "aqueduct": "Nuovo Vergine",
        "aqueduct_hint": "L'acquedotto Vergine alimenta la Fontana di Trevi e tutto il centro storico fin dal 19 a.C.",
        "icon": "⛲",
        "badges": ["centro storico", "acquedotto romano"],
        "search_tokens": "trevi pantheon campo marzio quirinale tridente centro storico vergine",
    },
    "roma_e_fiumicino_zona_5_acqua_marcia": {
        "display_name": "Roma Sud-Est (acquedotto Marcia)",
        "area": "Tuscolano, Appio Latino, San Giovanni",
        "aqueduct": "Acqua Marcia",
        "aqueduct_hint": "Acquedotto romano del 144 a.C.: il nome viene dal pretore Quinto Marcio Re, non dalla qualità dell'acqua.",
        "icon": "🏺",
        "badges": ["Roma sud-est", "acquedotto storico"],
        "search_tokens": "tuscolano appio latino san giovanni re di roma furio camillo arco di travertino acqua marcia",
    },
    "roma_e_fiumicino_zona_6_appio_alessandrino_hc": {
        "display_name": "Cinecittà e Quadraro",
        "area": "Roma Sud-Est · alta concentrazione",
        "aqueduct": "Appio-Alessandrino",
        "icon": "🎬",
        "badges": ["Roma sud-est", "HC"],
        "search_tokens": "cinecitta quadraro tuscolano numidio quadrato appio alessandrino",
    },
    "roma_e_fiumicino_zona_7_appio_alessandrino_lc": {
        "display_name": "Don Bosco e Tuscolano Sud",
        "area": "Roma Sud-Est · bassa concentrazione",
        "aqueduct": "Appio-Alessandrino",
        "icon": "🏘️",
        "badges": ["Roma sud-est", "LC"],
        "search_tokens": "don bosco tuscolano sud lucio sestio giulio agricola subaugusta appio alessandrino",
    },
    "roma_e_fiumicino_zona_8_acqua_marcia_+_peschiera_capore": {
        "display_name": "Zone miste centro-sud",
        "area": "Roma · rete mista (Marcia + Peschiera)",
        "aqueduct": "Acqua Marcia + Peschiera-Capore",
        "icon": "🔀",
        "badges": ["rete mista"],
        "search_tokens": "appio pignatelli ardeatina laurentina marconi ostiense acqua marcia peschiera capore",
    },
    "roma_e_fiumicino_zona_9_ostia_e_acilia": {
        "display_name": "Ostia, Acilia e Fiumicino",
        "area": "Litorale romano (Lido di Ostia, Acilia, Casal Palocco)",
        "aqueduct": "Peschiera-Capore (rete litorale)",
        "icon": "🏖️",
        "badges": ["litorale", "Fiumicino"],
        "search_tokens": "ostia lido acilia casal palocco infernetto axa fiumicino isola sacra fregene",
    },
}


# ---------- decodifica acquedotti ----------
_AQUEDUCT_KEYS = {
    "ACQUA MARCIA": ("Acqua Marcia",
        "Storico acquedotto romano del 144 a.C., capta sorgenti dell'alto Aniene. "
        "Il nome deriva dal pretore Quinto Marcio Re."),
    "PESCHIERA CAPORE": ("Peschiera-Capore",
        "Principale acquedotto di Roma: sorgenti di Peschiera (Cittaducale, RI) "
        "e Capore. Fornisce ~70% dell'acqua della Capitale."),
    "PESCHIERA-CAPORE": ("Peschiera-Capore",
        "Principale acquedotto di Roma: sorgenti di Peschiera (Cittaducale, RI) "
        "e Capore. Fornisce ~70% dell'acqua della Capitale."),
    "APPIO ALESSANDRINO": ("Appio-Alessandrino",
        "Rete che integra l'apporto principale nella zona sud-est di Roma."),
    "APPIO-ALESSANDRINO": ("Appio-Alessandrino", ""),
    "NUOVO VERGINE": ("Nuovo Vergine",
        "Discende dallo storico acquedotto Vergine (19 a.C.), che ancora oggi alimenta la Fontana di Trevi."),
    "DOGANELLA": ("Doganella", "Sorgenti dei Castelli Romani (Frascati / Doganella)."),
    "CONSORZIO PESCHIERA": ("Consorzio Peschiera", "Diramazione dell'acquedotto Peschiera-Capore."),
    "VAS": ("VAS",
        "Vasca dell'acquedotto / serbatoio locale."),
    "NASC": ("NASC", "Captazione da sorgente locale (NASC = nascente)."),
    "HC": ("alta concentrazione (HC)", ""),
    "LC": ("bassa concentrazione (LC)", ""),
}


def _decode_aqueduct(raw: str) -> tuple[str, str]:
    """Restituisce (label_pretty, hint) dato un descrittore tipo 'ACQUA MARCIA + PESCHIERA CAPORE'."""
    s = (raw or "").strip().upper()
    if not s:
        return "", ""
    # Match composto "X + Y"
    if "+" in s:
        parts = [_decode_aqueduct(p.strip())[0] for p in s.split("+")]
        parts = [p for p in parts if p]
        if parts:
            return " + ".join(parts), ""
    for k, (lbl, hint) in _AQUEDUCT_KEYS.items():
        if k in s:
            return lbl, hint
    # fallback: titlecase
    return s.title(), ""


def _titlecase_it(s: str) -> str:
    """Title case italiano: minuscole su preposizioni/congiunzioni."""
    lowers = {"di", "da", "del", "della", "delle", "dei", "degli", "dello",
              "in", "il", "la", "lo", "le", "e", "ed", "al", "alla", "ai",
              "su", "sul", "sulla", "per", "con", "tra", "fra", "a"}
    out = []
    for i, w in enumerate(re.split(r"(\s+|[-])", s)):
        if not w or w.isspace() or w == "-":
            out.append(w); continue
        wl = w.lower()
        # mantieni S.Maria, S.Sebastiano, ecc.
        if wl in lowers and i > 0:
            out.append(wl)
        elif "." in w and len(w) <= 3 and not re.match(r"^s\.?$", wl, re.I):
            out.append(w.upper())
        else:
            out.append(wl.capitalize())
    return "".join(out).replace("  ", " ").strip()


def _parse_name_parts(raw_name: str) -> tuple[str, str | None]:
    """Da 'agosta_zona_2_madonna_della_pace' → ('Agosta', 'Madonna della Pace').
       Da 'arsoli_zona_1' → ('Arsoli', None)."""
    s = raw_name or ""
    m = re.match(r"^(?P<com>[a-z_.]+?)_zona_(?P<n>\d+)(?:_(?P<loc>.+))?$", s, re.I)
    if not m:
        return _titlecase_it(s.replace("_", " ")), None
    comune_raw = m.group("com").replace("_", " ")
    comune_raw = _expand_saint_str(comune_raw)
    comune = _titlecase_it(comune_raw)
    loc_raw = m.group("loc")
    if not loc_raw:
        return comune, None
    loc = loc_raw.replace("_", " ").replace("+", " e ")
    loc = _expand_saint_str(loc)
    return comune, _titlecase_it(loc)


def _expand_saint_str(s: str) -> str:
    """Espande 's. X' → 'Santa X' / 'San X' / 'Sant'X' in base al genere."""
    def _sub(m: re.Match) -> str:
        nxt = m.group(1)
        if nxt.lower().endswith("a"):
            return f"Santa {nxt}"
        if nxt[0].lower() in "aeiou":
            return f"Sant'{nxt}"
        # "Santo" davanti a s+consonante (Stefano, Spirito), z, x, ps, gn
        n = nxt.lower()
        if (len(n) >= 2 and n[0] == "s" and n[1] not in "aeiou") \
                or n[0] in "zx" or n.startswith("ps") or n.startswith("gn"):
            return f"Santo {nxt}"
        return f"San {nxt}"
    return re.sub(r"\bs\.\s*([A-Za-zÀ-ÿ]+)", _sub, s, flags=re.I)


def enrich_zone(raw_name: str, comune: str | None, zona_label: str | None) -> dict[str, Any]:
    """Punto di ingresso: arricchisce una zona con tutti i campi user-friendly."""
    # 1) Override curato Roma+Fiumicino
    if raw_name in ROMA_ZONES:
        curated = ROMA_ZONES[raw_name].copy()
        # Estraggo il numero zona dal raw_name
        m = re.search(r"_zona_(\d+)", raw_name)
        curated["zone_num"] = m.group(1) if m else ""
        curated["comune_label"] = "Roma e Fiumicino"
        # Hint acquedotto, se non già definito
        if "aqueduct_hint" not in curated and curated.get("aqueduct"):
            _, hint = _decode_aqueduct(curated["aqueduct"])
            if hint:
                curated["aqueduct_hint"] = hint
        return curated

    # 2) Parser automatico per le altre 265 zone
    parsed_comune, locality = _parse_name_parts(raw_name)
    com_display = _titlecase_it(_expand_saint_str(comune)) if comune else parsed_comune

    zone_num = ""
    aq_raw = ""
    if zona_label:
        m = re.match(r"^\s*(\d+)\s*(.*)$", str(zona_label).strip())
        if m:
            zone_num = m.group(1)
            aq_raw = m.group(2).strip()
    aqueduct, aqueduct_hint = _decode_aqueduct(aq_raw)

    # Display name: priorità alla località se presente, altrimenti "Zona N"
    if locality:
        display_name = locality
        area = com_display
    else:
        display_name = com_display
        area = f"Zona {zone_num}" if zone_num else ""

    icon = "🏘️"
    return {
        "display_name": display_name,
        "area": area,
        "aqueduct": aqueduct,
        "aqueduct_hint": aqueduct_hint,
        "zone_num": zone_num,
        "icon": icon,
        "badges": [],
        "comune_label": com_display,
        "search_tokens": f"{com_display} {locality or ''} {aqueduct}".lower(),
    }
