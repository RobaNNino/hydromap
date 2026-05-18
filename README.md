# HydroMap — Qualità dell'acqua Roma & Lazio

Webapp che **scarica i 275 PDF di qualità dell'acqua** pubblicati da Acea Ato 2
([qualita-acqua](https://www.aceaato2.a-acqua.it/qualita-acqua)), li **parsifica**
estraendo tutti i parametri di potabilità, e li **rimappa** su un'interattiva
mappa Leaflet del Lazio con polygon colorati per stato di conformità.

In più: pannello **news in tempo reale** alimentato da **Gemini** con grounding
Google Search per le ultime notizie italiane sull'acqua.

## Quick start

```powershell
# 1. installa le dipendenze python
pip install -r requirements.txt

# 2. scarica GeoJSON + tutti i PDF (multithread, ~1-2 min)
python backend/scrape.py

# 3. parsifica i PDF in backend/data/results.json (multiprocess)
python backend/parse_pdfs.py

# 4. avvia il server
python backend/app.py
# apri http://127.0.0.1:5000
```

## Struttura

```
HYDROMAP/
├── .env                    # GEMINI_API_KEY (NON committare!)
├── backend/
│   ├── scrape.py           # 1) scarica GeoJSON + PDF
│   ├── parse_pdfs.py       # 2) estrae i parametri
│   ├── app.py              # 3) Flask: /api/geojson /api/zone /api/news
│   └── data/               # PDF + GeoJSON + results.json
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js              # Leaflet + sidebar
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
