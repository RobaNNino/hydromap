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
    # ---------- Toscana (Nuove Acque) ----------
    {
        "id": "toscana_nuoveacque",
        "provider": "toscana_nuoveacque",
        "title": "Nuove Acque — Alto Valdarno (AR/SI)",
        "description": (
            "Nuove Acque S.p.A. gestisce il servizio idrico integrato nei "
            "comuni dell'Alto Valdarno (province di Arezzo e Siena). Pubblica "
            "le schede «Qualità dell'acqua» con i valori medi rilevati per "
            "ciascun acquedotto comunale."
        ),
        "url": "https://www.nuoveacque.it/qualita-dellacqua",
        "agency": "Nuove Acque S.p.A.",
        "ato": "Autorità Idrica Toscana — Conferenza Territoriale n.4 Alto Valdarno",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Toscana (GAIA) ----------
    {
        "id": "toscana_gaia",
        "provider": "toscana_gaia",
        "title": "GAIA — Toscana Nord (LU/MS/PT)",
        "description": (
            "GAIA S.p.A. gestisce il servizio idrico integrato nei comuni "
            "dell'Ambito Toscana Nord (Lucca, Massa-Carrara e montagna "
            "pistoiese). Pubblica i valori medi semestrali per ciascun punto "
            "di prelievo della rete acquedottistica."
        ),
        "url": "https://www.gaia-spa.it/analisiweb_v2/",
        "agency": "GAIA S.p.A.",
        "ato": "Autorità Idrica Toscana — Conferenza Territoriale n.1 Toscana Nord",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Toscana (Publiacqua) ----------
    {
        "id": "toscana_publiacqua",
        "provider": "toscana_publiacqua",
        "title": "Publiacqua - Medio Valdarno (FI/PO/PT/AR)",
        "description": (
            "Publiacqua S.p.A. gestisce il servizio idrico integrato in larga "
            "parte dell'Ambito Medio Valdarno. Pubblica schede semestrali con "
            "valori medi, limiti di legge e coordinate del punto/zona."
        ),
        "url": "https://www.publiacqua.it/qualita-acqua",
        "agency": "Publiacqua S.p.A.",
        "ato": "Autorita Idrica Toscana - Conferenza Territoriale n.3 Medio Valdarno",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Toscana (Acque) ----------
    {
        "id": "toscana_acque",
        "provider": "toscana_acque",
        "title": "Acque - Basso Valdarno",
        "description": (
            "Acque S.p.A. gestisce il servizio idrico integrato nell'Ambito "
            "Basso Valdarno. Pubblica schede RIS con parametri analitici, "
            "riferimenti normativi e decorrenza dei valori."
        ),
        "url": "https://www.acque.net/",
        "agency": "Acque S.p.A.",
        "ato": "Autorita Idrica Toscana - Conferenza Territoriale n.2 Basso Valdarno",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Toscana (ASA) ----------
    {
        "id": "toscana_asamap",
        "provider": "toscana_asamap",
        "title": "ASA - Costa Toscana (LI/PI/SI)",
        "description": (
            "ASA S.p.A. pubblica le etichette di qualita dell'acqua tramite "
            "il portale cartografico ASAmap, con geometrie ufficiali degli "
            "acquedotti e schede PDF per ciascuna zona."
        ),
        "url": "https://www.asamap.it/etichette",
        "agency": "ASA S.p.A.",
        "ato": "Autorita Idrica Toscana - Conferenza Territoriale n.5 Toscana Costa",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Toscana (Fiora) ----------
    {
        "id": "toscana_fiora",
        "provider": "toscana_fiora",
        "title": "Acquedotto del Fiora - Toscana Sud",
        "description": (
            "Acquedotto del Fiora S.p.A. pubblica schede di qualita acqua "
            "per zone e sistemi idrici nei comuni della Toscana meridionale."
        ),
        "url": "https://www.fiora.it/azienda/acqua-e-territorio/qualita-dellacqua/",
        "agency": "Acquedotto del Fiora S.p.A.",
        "ato": "Autorita Idrica Toscana - Conferenza Territoriale n.6 Ombrone",
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
    # ---------- Marche ----------
    {
        "id": "marche_apmgroup",
        "provider": "marche_apmgroup",
        "title": "APM Group — Macerata",
        "description": (
            "APM Group pubblica schede di qualità dell'acqua per punti di "
            "prelievo e zone di distribuzione nei comuni serviti."
        ),
        "url": "https://www.apmgroup.it/",
        "agency": "APM Group",
        "ato": "ATO 3 Marche Centro - Macerata",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "marche_assemspa",
        "provider": "marche_assemspa",
        "title": "A.S.SE.M. S.p.A. — San Severino Marche",
        "description": (
            "A.S.SE.M. S.p.A. pubblica rapporti di prova per i punti di "
            "campionamento della rete nei comuni serviti."
        ),
        "url": "https://www.assemspa.it/",
        "agency": "A.S.SE.M. S.p.A.",
        "ato": "ATO 3 Marche Centro - Macerata",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "marche_asteaspa",
        "provider": "marche_asteaspa",
        "title": "ASTEA S.p.A. — Osimo/Recanati",
        "description": (
            "ASTEA S.p.A. pubblica rapporti di analisi per casette dell'acqua "
            "e punti della rete nei comuni serviti."
        ),
        "url": "https://www.asteaspa.it/",
        "agency": "ASTEA S.p.A.",
        "ato": "ATO 3 Marche Centro - Macerata",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "marche_atac_civitanova",
        "provider": "marche_atac_civitanova",
        "title": "ATAC Civitanova — Civitanova Marche",
        "description": (
            "ATAC Civitanova S.p.A. pubblica rapporti di prova dell'acqua "
            "potabile distribuita tramite acquedotto pubblico comunale."
        ),
        "url": "https://www.atac-civitanova.it/",
        "agency": "ATAC Civitanova S.p.A.",
        "ato": "ATO 3 Marche Centro - Macerata",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "marche_vivaservizi",
        "provider": "marche_vivaservizi",
        "title": "Viva Servizi — Ancona",
        "description": (
            "Viva Servizi S.p.A. pubblica riepiloghi analitici per i comuni "
            "serviti nell'ambito di Ancona."
        ),
        "url": "https://www.vivaservizi.it/",
        "agency": "Viva Servizi S.p.A.",
        "ato": "ATO 2 Marche Centro - Ancona",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "marche_multiservizi",
        "provider": "marche_multiservizi",
        "title": "Marche Multiservizi — Marche Nord",
        "description": (
            "Marche Multiservizi S.p.A. pubblica schede di qualità dell'acqua "
            "per acquedotti e punti di prelievo nei comuni serviti."
        ),
        "url": "https://www.gruppomarchemultiservizi.it/",
        "agency": "Marche Multiservizi S.p.A.",
        "ato": "ATO 1 Marche Nord - Pesaro e Urbino",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "marche_ciip",
        "provider": "marche_ciip",
        "title": "CIIP — Ascoli Piceno e Fermo",
        "description": (
            "CIIP S.p.A. (Cicli Integrati Impianti Primari) pubblica i referti "
            "delle analisi per utenza, sorgenti e pozzi del Piceno."
        ),
        "url": "https://www.ciip.it/",
        "agency": "CIIP S.p.A.",
        "ato": "ATO 5 Marche Sud - Ascoli Piceno e Fermo",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "iren_acqua",
        "provider": "iren_acqua",
        "title": "IREN Acqua — Emilia, Liguria, Piemonte",
        "description": (
            "Il Gruppo IREN pubblica i valori medi semestrali per comune e "
            "zona di distribuzione nei territori serviti (Piacenza, Parma, "
            "Reggio Emilia, Genova, Vercelli)."
        ),
        "url": "https://www.gruppoiren.it/it/i-nostri-servizi/servizio-idrico-integrato/qualita-dell-acqua.html",
        "agency": "Gruppo IREN",
        "ato": "Gruppo IREN - Emilia-Romagna, Liguria, Piemonte",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "emiliambiente",
        "provider": "emiliambiente",
        "title": "EmiliAmbiente — Bassa parmense",
        "description": (
            "EmiliAmbiente S.p.A. pubblica le analisi dell'acqua al punto di "
            "consegna per gli 11 comuni della bassa parmense serviti."
        ),
        "url": "https://www.emiliambiente.it/",
        "agency": "EmiliAmbiente S.p.A.",
        "ato": "ATERSIR - Emilia-Romagna (bassa parmense)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "montagna2000",
        "provider": "montagna2000",
        "title": "Montagna 2000 — Appennino parmense",
        "description": (
            "Montagna 2000 S.p.A. pubblica i referti per ciascun acquedotto "
            "delle valli di Taro e Ceno (Appennino parmense)."
        ),
        "url": "https://www.montagna2000.com/",
        "agency": "Montagna 2000 S.p.A.",
        "ato": "ATERSIR - Emilia-Romagna (Appennino parmense)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "arcareggio",
        "provider": "arcareggio",
        "title": "ARCA Reggio — Provincia di Reggio Emilia",
        "description": (
            "ARCA Reggio, subentrata a IRETI nella gestione idrica reggiana, "
            "pubblica i valori medi semestrali per ogni zona di distribuzione."
        ),
        "url": "https://www.arcareggio.it/i-nostri-servizi/qualita-dell-acqua.html",
        "agency": "ARCA Reggio",
        "ato": "ATERSIR - Emilia-Romagna (provincia di Reggio Emilia)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "aimag",
        "provider": "aimag",
        "title": "AIMAG — Modena e Mantova",
        "description": (
            "AIMAG S.p.A. pubblica schede semestrali sulla qualità dell'acqua "
            "distribuita (Carpi, Campogalliano, Cognento, Revere)."
        ),
        "url": "https://www.aimag.it/",
        "agency": "AIMAG S.p.A.",
        "ato": "ATERSIR Emilia-Romagna / ATO Mantova",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "sorgeaqua",
        "provider": "sorgeaqua",
        "title": "SorgeAqua — Modena/Bologna",
        "description": (
            "SorgeAqua S.r.l. pubblica referti periodici per i comuni di "
            "Crevalcore, Finale Emilia, Nonantola, Ravarino e Sant'Agata "
            "Bolognese."
        ),
        "url": "https://www.sorgeaqua.it/",
        "agency": "SorgeAqua S.r.l.",
        "ato": "ATERSIR - Emilia-Romagna (Modena/Bologna)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "toano",
        "provider": "toano",
        "title": "AST — Azienda Speciale Toano",
        "description": (
            "L'Azienda Speciale del Comune di Toano (RE) pubblica i rapporti "
            "di prova dei punti di campionamento delle frazioni (serbatoi e "
            "pozzetti)."
        ),
        "url": "https://www.comune.toano.re.it/",
        "agency": "AST - Azienda Speciale Toano",
        "ato": "Comune di Toano (RE)",
        "type": "Rapporti di laboratorio",
        "scraped": True,
    },
    {
        "id": "cadf",
        "provider": "cadf",
        "title": "CADF — Basso ferrarese",
        "description": (
            "CADF S.p.A. pubblica schede trimestrali sulla qualità dell'acqua "
            "per gli 11 comuni del Delta del Po ferrarese."
        ),
        "url": "https://www.cadf.it/",
        "agency": "CADF S.p.A.",
        "ato": "ATERSIR - Emilia-Romagna (basso ferrarese)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "romagnacque",
        "provider": "romagnacque",
        "title": "Romagna Acque — Società delle Fonti",
        "description": (
            "Romagna Acque gestisce le fonti e la rete all'ingrosso della "
            "Romagna (diga di Ridracoli e impianti): analisi dei punti di "
            "consegna e dei serbatoi nelle province di FC, RN e RA."
        ),
        "url": "https://www.romagnacque.it/",
        "agency": "Romagna Acque - Società delle Fonti S.p.A.",
        "ato": "Romagna (FC/RN/RA) - Società delle Fonti",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "comuniriuniti",
        "provider": "comuniriuniti",
        "title": "AS Comuni Riuniti — Montecopiolo",
        "description": (
            "L'Azienda Speciale Comuni Riuniti pubblica i rapporti di prova "
            "dei punti di campionamento di Montecopiolo (RN)."
        ),
        "url": "https://www.comunemontecopiolo.it/",
        "agency": "AS Comuni Riuniti",
        "ato": "Comune di Montecopiolo (RN)",
        "type": "Rapporti di laboratorio",
        "scraped": True,
    },
    {
        "id": "gruppohera",
        "provider": "gruppohera",
        "title": "Gruppo Hera — Che acqua bevi",
        "description": (
            "Il Gruppo Hera pubblica i valori medi per zona di fornitura "
            "idropotabile nei territori serviti (Emilia-Romagna e oltre): "
            "ogni zona riporta i parametri dell'acqua distribuita."
        ),
        "url": "https://www.gruppohera.it/offerte-e-servizi/casa/acqua/che-acqua-bevi",
        "agency": "Gruppo Hera",
        "ato": "ATERSIR Emilia-Romagna e territori Gruppo Hera",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "sanmarino_aass",
        "provider": "sanmarino_aass",
        "title": "AASS — Repubblica di San Marino",
        "description": (
            "L'Azienda Autonoma di Stato per i Servizi Pubblici pubblica i "
            "valori medi semestrali dell'acqua potabile per ciascuno dei "
            "9 castelli sammarinesi."
        ),
        "url": "https://www.aass.sm/site/home/reti/acqua/qualita-dellacqua.html",
        "agency": "AASS",
        "ato": "Repubblica di San Marino",
        "type": "Portale gestore",
        "scraped": True,
    },
    # ---------- Veneto / Friuli-Venezia Giulia ----------
    {
        "id": "ags",
        "provider": "ags",
        "title": "Azienda Gardesana Servizi — Garda veronese",
        "description": (
            "AGS gestisce il servizio idrico della sponda veronese del Garda "
            "e della Valpolicella: schede semestrali con i parametri medi "
            "dell'acqua erogata per comune."
        ),
        "url": "https://www.azienda-gardesana.it/",
        "agency": "Azienda Gardesana Servizi S.p.A.",
        "ato": "ATO Veronese — Garda (VR)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "mediochiampo",
        "provider": "mediochiampo",
        "title": "Medio Chiampo — Valle del Chiampo",
        "description": (
            "Medio Chiampo S.p.A. serve i comuni della bassa valle del Chiampo "
            "(VI). Rapporti di prova del laboratorio acquevenete, con focus sul "
            "monitoraggio PFAS."
        ),
        "url": "https://www.mediochiampo.it/",
        "agency": "Medio Chiampo S.p.A.",
        "ato": "AATO Bacchiglione — Valle del Chiampo (VI)",
        "type": "Rapporti di laboratorio",
        "scraped": True,
    },
    {
        "id": "piaveservizi",
        "provider": "piaveservizi",
        "title": "Piave Servizi — Sinistra Piave",
        "description": (
            "Piave Servizi gestisce l'acquedotto della Sinistra Piave (TV): "
            "tabella semestrale dei parametri caratteristici per zona di "
            "distribuzione."
        ),
        "url": "https://www.piaveservizi.it/",
        "agency": "Piave Servizi S.r.l.",
        "ato": "ATO Veneto Orientale (TV)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "gruppoveritas",
        "provider": "gruppoveritas",
        "title": "Gruppo Veritas — Venezia",
        "description": (
            "Veritas S.p.A. è il gestore idrico dell'area metropolitana di "
            "Venezia e del Veneziano: valori medi dell'acqua potabile per "
            "comune, aggiornati a semestre."
        ),
        "url": "https://www.gruppoveritas.it/",
        "agency": "Veritas S.p.A.",
        "ato": "ATO Laguna di Venezia (VE)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "acquevenete",
        "provider": "acquevenete",
        "title": "Acque Venete — Polesine e Bassa Padovana",
        "description": (
            "acquevenete S.p.A. serve il Polesine e la bassa padovana: portale "
            "qualità con l'ultimo valore dei parametri per comune e centrale di "
            "produzione."
        ),
        "url": "https://www.acquevenete.it/",
        "agency": "acquevenete S.p.A.",
        "ato": "ATO Polesine / Bacchiglione (RO/PD)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "acqueveronesi",
        "provider": "acqueveronesi",
        "title": "Acque Veronesi — Veronese",
        "description": (
            "Acque Veronesi gestisce il servizio idrico integrato della "
            "provincia di Verona: schede per comune e punto di prelievo con i "
            "valori dei parametri."
        ),
        "url": "https://acqueveronesi.it/",
        "agency": "Acque Veronesi S.c.a r.l.",
        "ato": "ATO Veronese (VR)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "lta",
        "provider": "lta",
        "title": "LTA — Lemene (Veneto orientale / Pordenone)",
        "description": (
            "LTA S.p.A. (Livenza Tagliamento Acque) serve il Veneto orientale e "
            "il Pordenonese: schede qualità con valore medio, limite di legge e "
            "frequenza di monitoraggio."
        ),
        "url": "https://www.lta.it/schede-qualita",
        "agency": "LTA S.p.A.",
        "ato": "ATO Lemene (Veneto orientale / PN)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "sibspa",
        "provider": "sibspa",
        "title": "SIB — Alto Veneto (Belluno)",
        "description": (
            "Società Intercomunale Bellunese (SIB) gestisce l'acquedotto della "
            "provincia di Belluno: valori medi semestrali per comune e zona di "
            "distribuzione."
        ),
        "url": "https://sibspa.it/",
        "agency": "SIB S.p.A.",
        "ato": "ATO Alto Veneto (BL)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "viacqua",
        "provider": "viacqua",
        "title": "Viacqua — Vicentino",
        "description": (
            "Viacqua S.p.A. gestisce il servizio idrico integrato della "
            "provincia di Vicenza: valori dei parametri dell'acqua distribuita "
            "per comune e zona."
        ),
        "url": "https://www.viacqua.it/it/clienti/acquedotto/qualita-dell-acqua/",
        "agency": "Viacqua S.p.A.",
        "ato": "ATO Bacchiglione (VI)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "acquedelchiampo",
        "provider": "acquedelchiampo",
        "title": "Acque del Chiampo — Valle del Chiampo",
        "description": (
            "Acque del Chiampo S.p.A. serve l'alta valle del Chiampo e l'Ovest "
            "Vicentino: schede per distretto con valore medio rilevato e valore "
            "di riferimento di legge."
        ),
        "url": "https://www.acquedelchiampo.it/",
        "agency": "Acque del Chiampo S.p.A.",
        "ato": "AATO Valle del Chiampo (VI)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "acegasapsamga",
        "provider": "acegasapsamga",
        "title": "AcegasApsAmga — Padova, Saccisica e Trieste (gruppo Hera)",
        "description": (
            "AcegasApsAmga (gruppo Hera) gestisce il servizio idrico di Padova, "
            "della Saccisica e di Trieste: caratteristiche di qualità medie "
            "mensili dell'acqua per zona di fornitura."
        ),
        "url": "https://www.acegasapsamga.it/servizi/acqua/qualita-acqua-potabile",
        "agency": "AcegasApsAmga S.p.A.",
        "ato": "Padova / Saccisica (PD-VE) e Trieste (TS)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "etra",
        "provider": "etra",
        "title": "Gruppo ETRA — Alta Padovana e Bassano",
        "description": (
            "ETRA S.p.A. (Energia Territorio Risorse Ambientali) gestisce il "
            "servizio idrico dell'Alta Padovana, del Bassanese e del Camposampierese "
            "(PD/VI): rapporti di prova del laboratorio ETRA per punto di prelievo."
        ),
        "url": "https://www.etraspa.it/",
        "agency": "ETRA S.p.A. Società Benefit",
        "ato": "ATO Brenta — Alta Padovana e Bassano (PD/VI)",
        "type": "Rapporti di laboratorio",
        "scraped": True,
    },
    {
        "id": "ats",
        "provider": "ats",
        "title": "Alto Trevigiano Servizi — Trevigiano",
        "description": (
            "ATS gestisce il servizio idrico di gran parte della provincia di "
            "Treviso (Montebelluna, Castelfranco, Valdobbiadene, Asolo…). I dati "
            "di qualità sono pubblicati per coordinate via API; qui sono "
            "ricondotti al comune per point-in-polygon."
        ),
        "url": "https://altotrevigianoservizi.it/mappe-ats/qualita-acqua.html",
        "agency": "Alto Trevigiano Servizi S.r.l.",
        "ato": "ATO Veneto Orientale — Trevigiano (TV/BL)",
        "type": "Portale gestore",
        "scraped": True,
    },
    {
        "id": "cafc",
        "provider": "cafc",
        "title": "CAFC — Friuli Centrale",
        "description": (
            "CAFC S.p.A. (Consorzio Acquedotto Friuli Centrale) gestisce il "
            "servizio idrico di gran parte del Friuli Centrale (Udine e provincia, "
            "Carnia): rapporti di prova del laboratorio FRIULAB per punto di "
            "prelievo, ricondotti al comune."
        ),
        "url": "https://www.cafcspa.com/it/qualita-acqua",
        "agency": "CAFC S.p.A.",
        "ato": "ATO Centrale Friuli (UD)",
        "type": "Rapporti di laboratorio",
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

