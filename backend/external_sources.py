"""
Registry delle fonti ufficiali utilizzate da AcquaMap.

Contiene:
  - i gestori idrici del Lazio (con metadato `provider` allineato agli ID
    usati nei dataset di backend per il badge in UI),
  - le fonti istituzionali (Ministero della Salute, Città Metropolitana).

Il campo `provider` è valorizzato solo per le voci che corrispondono ad un
gestore idrico tracciato nei dati zona; le altre voci sono link informativi.
Il campo `ato` indica l'Ambito Territoriale Ottimale del Lazio, quando
applicabile.
"""
from __future__ import annotations


OFFICIAL_SOURCES = [
    # ---------- Gestori idrici del Lazio ----------
    {
        "id": "acea_ato2",
        "provider": "acea_ato2",
        "title": "Acea ATO 2 — Roma e provincia",
        "description": (
            "Gestore del Servizio Idrico Integrato dell'ATO 2 Lazio Centrale "
            "(Roma e 111 comuni della Città Metropolitana). I dati AcquaMap "
            "su Roma e l'hinterland provengono da questo portale."
        ),
        "url": "https://www.aceaato2.a-acqua.it/qualita-acqua",
        "agency": "Acea ATO 2 S.p.A.",
        "ato": "ATO 2 — Lazio Centrale",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "acea_ato5",
        "provider": "acea_ato5",
        "title": "Acea ATO 5 — Frosinone e provincia",
        "description": (
            "Gestore del Servizio Idrico Integrato dell'ATO 5 Lazio Meridionale "
            "(86 comuni della provincia di Frosinone). Stesso template Acea: "
            "consultabile per indirizzo o CAP."
        ),
        "url": "https://www.aceaato5.a-acqua.it/qualita-acqua",
        "agency": "Acea ATO 5 S.p.A.",
        "ato": "ATO 5 — Lazio Meridionale (Frosinone)",
        "type": "Portale gestore",
        "scraped": False,
    },
    {
        "id": "acqualatina",
        "provider": "acqualatina",
        "title": "Acqualatina — Latina e Frosinone sud",
        "description": (
            "Gestore dell'ATO 4 Lazio Meridionale (provincia di Latina e parte "
            "della provincia di Frosinone). Pubblica i valori medi annui per "
            "ciascuno dei comuni serviti."
        ),
        "url": "https://www.acqualatina.it/qualita-dellacqua-per-comune/",
        "agency": "Acqualatina S.p.A.",
        "ato": "ATO 4 — Lazio Meridionale (Latina)",
        "type": "Portale gestore",
        "scraped": False,
    },
    {
        "id": "talete",
        "provider": "talete",
        "title": "Talete — Viterbo e provincia",
        "description": (
            "Gestore dell'ATO 1 Lazio Nord (60 comuni della provincia di "
            "Viterbo). I dati di qualità sono pubblicati dalla ASL di Viterbo "
            "nel portale Arsenico/qualità delle acque."
        ),
        "url": "https://www.taletespa.eu/qualita-delle-acque/",
        "agency": "Talete S.p.A.",
        "ato": "ATO 1 — Lazio Nord (Viterbo)",
        "type": "Portale gestore",
        "scraped": False,
        "hint": "Per i valori dettagliati: https://www.asl.vt.it/Cittadino/arsenico/base.php",
    },
    {
        "id": "acqua_pubblica_sabina",
        "provider": "acqua_pubblica_sabina",
        "title": "Acqua Pubblica Sabina — Rieti e provincia",
        "description": (
            "Gestore dell'ATO 3 Lazio Centrale Rieti. Società totalmente "
            "pubblica. 65 comuni serviti (provincia di Rieti + sabina "
            "romana), 310 rapporti di prova del laboratorio Gruppo Maurizi "
            "parsati e geolocalizzati su poligoni ISTAT."
        ),
        "url": "https://www.acquapubblicasabina.it/index.php/qualita/shop/qualita-dell-acqua-per-comune",
        "agency": "Acqua Pubblica Sabina S.p.A.",
        "ato": "ATO 3 — Lazio Centrale (Rieti)",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Fonti istituzionali ----------
    {
        "id": "salute",
        "title": "Ministero della Salute — Acque destinate al consumo umano",
        "description": (
            "Mappa nazionale con i controlli ASL sull'acqua potabile. Cerca "
            "per comune per filtrare i campionamenti del territorio."
        ),
        "url": "https://www.portaleacque.salute.gov.it/PortaleAcquePubblico/mappa",
        "agency": "Ministero della Salute",
        "type": "Mappa interattiva",
        "hint": "Nella ricerca digita il comune → seleziona → clicca sui punti di campionamento.",
    },
    {
        "id": "g3w",
        "title": "Città Metropolitana Roma — Tutela delle acque",
        "description": (
            "Corridoi fluviali Tevere/Aniene, zone di rispetto delle "
            "captazioni, aree di salvaguardia idrogeologica."
        ),
        "url": "https://g3w-suite.cittametropolitanaroma.it/it/map/tutela-acque/",
        "agency": "Città Metropolitana di Roma Capitale",
        "type": "WebGIS",
    },
]


# Mappa rapida provider_id -> metadati gestore (label visibile + ATO).
PROVIDER_META: dict[str, dict] = {
    s["provider"]: {
        "label": s["title"],
        "agency": s["agency"],
        "ato": s.get("ato"),
        "url": s["url"],
    }
    for s in OFFICIAL_SOURCES
    if s.get("provider")
}

