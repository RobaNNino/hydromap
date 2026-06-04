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
    # ---------- Abruzzo ----------
    {
        "id": "abruzzo_cam",
        "provider": "abruzzo_cam",
        "title": "CAM S.p.A. — Marsica (AQ)",
        "description": (
            "Consorzio Acquedottistico Marsicano. Servizio idrico integrato "
            "per i 37 comuni della Marsica (provincia dell'Aquila). Valori "
            "analitici medi annuali con campionamento su rete di distribuzione."
        ),
        "url": "https://www.camspa.com/",
        "agency": "CAM S.p.A. — Consorzio Acquedottistico Marsicano",
        "ato": "ATO 2 — Marsica (AQ)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "abruzzo_ruzzo",
        "provider": "abruzzo_ruzzo",
        "title": "Ruzzo Reti S.p.A. — Teramano (TE)",
        "description": (
            "Gestore del Servizio Idrico Integrato per la provincia di Teramo "
            "(47 comuni). Rapporti di prova del laboratorio Astra Studio Chimico "
            "Associato di Teramo, accreditato ACCREDIA."
        ),
        "url": "https://www.ruzzo.it/",
        "agency": "Ruzzo Reti S.p.A.",
        "ato": "ATO 5 — Teramano",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "abruzzo_aca",
        "provider": "abruzzo_aca",
        "title": "ACA S.p.A. — Pescarese e Chietino (PE/CH)",
        "description": (
            "Azienda Comprensoriale Acquedottistica di Pescara. Gestisce il "
            "servizio idrico integrato per oltre 80 comuni nelle province di "
            "Pescara e Chieti, con laboratorio analisi a Chieti."
        ),
        "url": "https://www.acaspa.it/",
        "agency": "ACA S.p.A.",
        "ato": "ATO 4 — Pescarese",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "abruzzo_sasi",
        "provider": "abruzzo_sasi",
        "title": "SASI S.p.A. — Chietino-Vastese (CH)",
        "description": (
            "Società Abruzzese per il Servizio Idrico Integrato. Sede a Lanciano, "
            "gestisce il servizio idrico in 96 comuni del chietino-vastese con "
            "laboratorio interno di analisi (Ufficio Potabilità)."
        ),
        "url": "https://www.sasispa.it/",
        "agency": "SASI S.p.A.",
        "ato": "ATO 6 — Chietino",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "abruzzo_gransasso",
        "provider": "abruzzo_gransasso",
        "title": "Gran Sasso Acqua S.p.A. — Aquilano (AQ)",
        "description": (
            "Gran Sasso Acqua S.p.A. con sede a L'Aquila gestisce il servizio "
            "idrico integrato per il territorio aquilano (ATO 1), 42 comuni "
            "serviti dalla Sorgente del Gran Sasso. Pubblica report mensili "
            "delle analisi della fonte principale."
        ),
        "url": "https://www.gransassoacqua.it/analisi-acqua",
        "agency": "Gran Sasso Acqua S.p.A.",
        "ato": "ATO 1 — Aquilano",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Molise ----------
    {
        "id": "molise_acea",
        "provider": "molise_acea",
        "title": "Acea Molise — Campobasso e Isernia",
        "description": (
            "Acea Molise (Gruppo Acea) gestisce il servizio idrico integrato "
            "in numerosi comuni delle province di Campobasso e Isernia. "
            "Pubblica i rapporti di prova GRIM per ciascun punto di prelievo "
            "della rete acquedottistica regionale."
        ),
        "url": "https://www.aceamolise.a-acqua.it/qualita-acqua",
        "agency": "Acea Molise S.r.l.",
        "ato": "ATO Unico Molise",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Basilicata ----------
    {
        "id": "basilicata_al",
        "provider": "basilicata_al",
        "title": "Acquedotto Lucano — Basilicata",
        "description": (
            "Acquedotto Lucano S.p.A. gestisce il servizio idrico integrato "
            "in tutti i 131 comuni della Basilicata. Pubblica i rapporti di "
            "prova per i punti di prelievo (serbatoi e abitati) della rete "
            "acquedottistica regionale."
        ),
        "url": "https://www.acquedottolucano.it/qualita-acqua",
        "agency": "Acquedotto Lucano S.p.A.",
        "ato": "EGRIB — Ente di Governo per i Rifiuti e le Risorse Idriche della Basilicata",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Lazio (extra) ----------
    {
        "id": "lazio_idrica_ardea",
        "provider": "lazio_idrica_ardea",
        "title": "Idrica — Ardea (RM)",
        "description": (
            "Idrica S.p.A. gestisce il servizio idrico del comune di Ardea "
            "(Roma). Pubblica i rapporti di prova per i punti di prelievo "
            "della rete cittadina (fontanelle e serbatoi)."
        ),
        "url": "https://www.idricaspa.it/",
        "agency": "Idrica S.p.A.",
        "ato": "ATO 2 — Lazio Centrale (Roma)",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Campania ----------
    {
        "id": "campania_abc_napoli",
        "provider": "campania_abc_napoli",
        "title": "ABC Napoli — Acqua Bene Comune",
        "description": (
            "ABC Napoli S.p.A. (Acqua Bene Comune) gestisce il servizio idrico "
            "della città di Napoli. Pubblica i report semestrali dei punti di "
            "campionamento (fontanelle e prese pubbliche)."
        ),
        "url": "https://www.abc.napoli.it/qualita-dellacqua",
        "agency": "ABC Napoli S.p.A.",
        "ato": "ATO 2 — Napoli Volturno",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "campania_alto_calore",
        "provider": "campania_alto_calore",
        "title": "Alto Calore Servizi — Avellino / Benevento",
        "description": (
            "Alto Calore Servizi S.p.A. gestisce il servizio idrico integrato "
            "per oltre 120 comuni delle province di Avellino e Benevento. "
            "Pubblica un report semestrale per ciascun comune."
        ),
        "url": "https://www.altocalore.it/qualita-acqua/",
        "agency": "Alto Calore Servizi S.p.A.",
        "ato": "ATO 1 — Calore Irpino",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "campania_gesesa",
        "provider": "campania_gesesa",
        "title": "GESESA — Benevento e Sannio",
        "description": (
            "GESESA S.p.A. gestisce il servizio idrico della città di "
            "Benevento e di una ventina di comuni del Sannio. Pubblica un "
            "monitoraggio annuale con riferimento al D.Lgs. 18/2023."
        ),
        "url": "https://www.gesesa.it/qualita-dellacqua/",
        "agency": "GESESA S.p.A.",
        "ato": "ATO 1 — Calore Irpino",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "campania_gori",
        "provider": "campania_gori",
        "title": "GORI — Vesuviano e Penisola Sorrentina",
        "description": (
            "GORI S.p.A. gestisce il servizio idrico integrato di 75 comuni "
            "tra Napoli e Salerno (area vesuviana, agro sarnese-nocerino, "
            "penisola sorrentina). Pubblica certificati di garanzia semestrali."
        ),
        "url": "https://www.goriacqua.com/qualita-dellacqua/",
        "agency": "GORI S.p.A.",
        "ato": "ATO 3 — Sarnese Vesuviano",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "campania_itl_spa",
        "provider": "campania_itl_spa",
        "title": "I.T.L. S.p.A. — Casertano",
        "description": (
            "I.T.L. S.p.A. (Caserta) gestisce il servizio idrico per numerosi "
            "comuni della provincia di Caserta. Pubblica rapporti di prova "
            "puntuali per ciascun sito di campionamento, eseguiti dal "
            "laboratorio Natura S.r.l."
        ),
        "url": "https://www.itlspa.it/",
        "agency": "I.T.L. S.p.A.",
        "ato": "ATO 2 — Napoli Volturno (CE)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "campania_nepta_acqua",
        "provider": "campania_nepta_acqua",
        "title": "Nepta Acqua — Caserta",
        "description": (
            "Nepta Acqua gestisce il servizio idrico del comune di Caserta, "
            "pubblicando i risultati dei controlli per ciascun punto di "
            "prelievo della rete cittadina."
        ),
        "url": "",
        "agency": "Nepta Acqua S.r.l.",
        "ato": "Caserta (gestione locale)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "campania_salerno_sistemi",
        "provider": "campania_salerno_sistemi",
        "title": "Salerno Sistemi — Salerno",
        "description": (
            "Salerno Sistemi S.p.A. gestisce il servizio idrico della città di "
            "Salerno, pubblicando dati per ciascun quartiere/zona della rete."
        ),
        "url": "https://serviziidrici.grupposistemisalerno.it/qualita-dellacqua/",
        "agency": "Salerno Sistemi S.p.A.",
        "ato": "ATO 4 — Sele",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "campania_ausino",
        "provider": "campania_ausino",
        "title": "Ausino — Costiera Amalfitana e Picentini (SA)",
        "description": (
            "Ausino S.p.A. Servizi Idrici Integrati gestisce il servizio idrico "
            "per i comuni della Costiera Amalfitana e dei Monti Picentini in "
            "provincia di Salerno. Pubblica un report per ciascun comune servito."
        ),
        "url": "https://www.ausino.it/",
        "agency": "Ausino S.p.A.",
        "ato": "ATO 4 — Sele (SA)",
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

