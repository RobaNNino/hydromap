# AcquaMap — Qualità dell'acqua Roma & Lazio

Webapp che **scarica i PDF di qualità dell'acqua** dei principali gestori del
Lazio, li **parsifica** estraendo tutti i parametri di potabilità, e li
**rimappa** su un'interattiva mappa Leaflet con polygon colorati per stato di
conformità. Attualmente: **499 zone** servite (Acea ATO 2 + ATO 5 + Acqualatina).

In più: pannello **news in tempo reale** alimentato da **Gemini** con grounding
Google Search per le ultime notizie italiane sull'acqua.

## Quick start

```powershell
# 1. installa le dipendenze python
pip install -r requirements.txt

# 2. scarica GeoJSON + PDF di ciascun provider
python backend/scrape.py                          # Acea ATO 2 — Roma (default)
python backend/scrape.py --provider acea_ato5     # Acea ATO 5 — Frosinone
python backend/scrape_acqualatina.py              # Acqualatina — Latina (44 PDF)

# 3. parsifica TUTTI i PDF (Acea + Acqualatina) in backend/data/results.json
python backend/parse_pdfs.py

# 4. avvia il server
python backend/app.py
# apri http://127.0.0.1:5000
```

## Gestori idrici del Lazio

AcquaMap integra dati dai principali gestori del Lazio. Lo stato attuale:

| Gestore | Territorio | ATO | Stato |
|---|---|---|---|
| **Acea ATO 2** | Roma + 111 comuni | ATO 2 Lazio Centrale | ✅ 275 zone, PDF parsati |
| **Acea ATO 5** | Frosinone + 86 comuni | ATO 5 Lazio Meridionale | ✅ 180 zone, PDF parsati |
| **Acqualatina** | Latina + Frosinone sud | ATO 4 Lazio Meridionale | ✅ 44 zone (poligoni ISTAT), PDF parsati |
| **Talete** | Viterbo | ATO 1 Lazio Nord | 🔗 Link al portale + ASL VT |
| **Acqua Pubblica Sabina** | Rieti | ATO 3 Lazio Centrale | ✅ 65 comuni (poligoni ISTAT) — 310 rapporti laboratorio parsati (15 parametri per zona: microbiologici + chimico-fisici + organolettici) |

I link a tutti i gestori sono visibili nella tab **Info → Fonti dei dati**.
I poligoni Acqualatina sono generati dai confini comunali ISTAT (openpolis):
quando il PDF copre solo una porzione del comune (Latina Nord/Sud, frazioni
di Aprilia), tutte le zone usano lo stesso poligono comunale e si
distinguono nella tooltip via `zona_label`.

## Freschezza dei dati

Ogni zona indica la **data dell'analisi** (campo `periodo` estratto dal PDF) con
un badge colorato:

- 🟢 **Nuova** — analisi degli ultimi 6 mesi
- 🟡 **In scadenza** — analisi tra 6 e 12 mesi
- 🔴 **Vecchia** — analisi più vecchia di 12 mesi

Le soglie sono configurabili via env: `FRESH_MAX_MONTHS` (default 6) e
`FRESH_WARN_MONTHS` (default 12).


## Struttura

```
ACQUAMAP/
├── .env                    # GEMINI_API_KEY (NON committare!)
├── backend/
│   ├── scrape.py              # 1a) scarica GeoJSON + PDF Acea (ATO 2 e 5)
│   ├── scrape_acqualatina.py  # 1b) scarica PDF Acqualatina + costruisce poligoni ISTAT
│   ├── parse_pdfs.py          # 2)  estrae i parametri (dispatch per provider)
│   ├── app.py                 # 3)  Flask: /api/geojson /api/zone /api/news
│   └── data/                  # PDF + GeoJSON + results.json
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js                 # Leaflet + sidebar
```

## API

| Endpoint                | Descrizione                                                |
|-------------------------|------------------------------------------------------------|
| `GET /api/geojson`      | FeatureCollection con `status`, `fill`, `stroke` arricchiti |
| `GET /api/zone/<name>`  | Dettaglio parametri di una zona                            |
| `GET /api/pdf/<name>`   | Stream del PDF originale                                   |
| `GET /api/news?limit=6` | News acqua in tempo reale (Gemini + Google Search)         |

## Sicurezza

⚠️ La chiave Gemini in `.env` è **client privata**: ruotala se è stata esposta
nella chat. Il file `.env` è in `.gitignore`.
