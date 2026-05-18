# 🚀 HydroMap — Guida al deploy

Backend Flask su **Render** (gratis) + frontend statico su **Netlify** (gratis).

---

## 📦 Cosa pubblichi e dove

| Componente | Dove | Come |
|---|---|---|
| Backend Python (Flask + scraper + Gemini) | **Render** | Web Service da repo GitHub |
| Frontend HTML/JS (mappa Leaflet) | **Netlify** | Sito statico da repo GitHub |
| Dati (275 PDF, results.json, GeoJSON, nasoni) | Insieme al backend su Render | committati nel repo |

---

## 🪜 Step 0 — Prerequisiti

1. Account [GitHub](https://github.com)
2. Account [Render](https://render.com) (login con GitHub)
3. Account [Netlify](https://app.netlify.com/signup) (login con GitHub)
4. **GEMINI_API_KEY** (https://aistudio.google.com/apikey) — la tua è già nel `.env` locale

---

## 🪜 Step 1 — Pushare il progetto su GitHub

Dalla cartella `HYDROMAP`:

```powershell
# Inizializza repo (se non già fatto)
git init
git add .
git commit -m "HydroMap: prepare for deploy"

# Crea il repo su GitHub via web (es. https://github.com/TUO_USER/hydromap)
# poi:
git branch -M main
git remote add origin https://github.com/TUO_USER/hydromap.git
git push -u origin main
```

> ⚠️ Il repo peserà **~55 MB** (48 MB di PDF + 2 MB di results.json + 4 MB di GeoJSON). È sotto la soglia GitHub di 100 MB per repo. **Non** usare `git lfs`, non serve.
>
> ⚠️ Verifica che `.env` **non** sia nel commit (è in `.gitignore`). Esegui `git status` prima di pushare.

---

## 🪜 Step 2 — Deploy backend su Render

### Opzione A — Blueprint automatico (consigliata)

1. Vai su https://dashboard.render.com/
2. **New +** → **Blueprint**
3. Connetti il tuo repo GitHub `hydromap`
4. Render rileva `render.yaml` e propone il servizio `hydromap-api`
5. Clic su **Apply**
6. Quando richiede `GEMINI_API_KEY`, **incolla la tua chiave**
7. Aspetta il primo build (~3-5 min)
8. A fine build hai un URL tipo `https://hydromap-api.onrender.com`

### Opzione B — Manuale

1. **New +** → **Web Service** → connetti il repo
2. Settings:
   - **Name**: `hydromap-api`
   - **Region**: Frankfurt (più vicina)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn backend.app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
   - **Plan**: Free
3. **Environment** → aggiungi:
   - `GEMINI_API_KEY` = la tua chiave
   - `GEMINI_MODEL` = `gemini-2.5-flash`
   - `GEMINI_NEWS_MODEL` = `gemini-2.5-pro`
   - `NEWS_MAX_AGE_DAYS` = `30`
   - `PYTHON_VERSION` = `3.11.9`
   - `CORS_ORIGINS` = `*` (per ora; ristringi dopo Step 4)
4. **Create Web Service**

### Verifica backend
Apri nel browser: `https://hydromap-api.onrender.com/api/geojson`
Deve restituire JSON con le zone.

> 💤 **Render Free** mette in pausa dopo 15 min di inattività. La prima richiesta dopo il sonno richiede ~30 s di cold start. Per evitare: piano **Starter** ($7/mese) o un cron esterno tipo [cron-job.org](https://cron-job.org/) che pinga `/api/geojson` ogni 10 min.

---

## 🪜 Step 3 — Deploy frontend su Netlify

1. Vai su https://app.netlify.com/
2. **Add new site** → **Import an existing project** → **Deploy with GitHub**
3. Scegli il repo `hydromap`
4. Settings (già letti da `netlify.toml`):
   - **Base directory**: lascia vuoto
   - **Build command**: lascia vuoto
   - **Publish directory**: `frontend`
5. **Deploy site**
6. Netlify ti assegna un URL tipo `https://random-name-12345.netlify.app`
7. (Opzionale) **Site settings** → **Change site name** → es. `hydromap`

### ⚠️ IMPORTANTE — Collegare frontend e backend

Il frontend deve sapere dove sta il backend. Modifica [frontend/index.html](frontend/index.html):

```html
<meta name="api-base" content="https://hydromap-api.onrender.com" />
```

(Sostituisci con il **tuo** URL Render dello Step 2.)

Poi commit + push:
```powershell
git add frontend/index.html
git commit -m "Set production API base URL"
git push
```
Netlify ridistribuirà automaticamente in ~30 secondi.

---

## 🪜 Step 4 — Hardening (consigliato)

### Ristringi CORS al solo dominio Netlify

Su Render → **Environment** → modifica:
```
CORS_ORIGINS=https://hydromap.netlify.app
```
(Salva → Render riavvia il servizio.)

### Dominio personalizzato (opzionale)

- **Netlify** → Site → Domain settings → Add custom domain → segui istruzioni DNS
- **Render** → Settings → Custom Domain (richiede piano Starter)

---

## 🧪 Test end-to-end

Apri `https://hydromap.netlify.app`:

- [ ] La mappa carica le zone (chiamata `/api/geojson` al backend Render)
- [ ] Click su una zona → sidebar con dati (chiamata `/api/zone/...`)
- [ ] Tab **News** → carica notizie da Gemini
- [ ] Tab **Dashboard** → grafici Chart.js
- [ ] Tab **Chat AI** → risposta dal modello
- [ ] Link "📄 PDF originale" → apre il PDF servito da Render

### Console del browser
Apri DevTools (F12) → Network. Devi vedere chiamate XHR a `https://hydromap-api.onrender.com/api/...` con status 200.

---

## 🛠 Troubleshooting

| Problema | Causa | Fix |
|---|---|---|
| **CORS error** in console | `CORS_ORIGINS` non include il dominio Netlify | Su Render aggiungi il dominio esatto, virgola-separato |
| **404 su /api/pdf/...** | `<meta name="api-base">` vuoto o sbagliato | Verifica che punti all'URL Render |
| **Prima richiesta lenta (~30s)** | Render Free in sleep | Normale. Piano Starter o ping esterno |
| **Build Render fallisce su pdfplumber** | Python troppo nuovo/vecchio | Verifica `runtime.txt` = `python-3.11.9` |
| **Mappa vuota** | `results.json` o GeoJSON non nel repo | Controlla `git ls-files backend/data/` |
| **Memoria saturata** su Render Free | Workers troppi | Riduci a `--workers 1` in `render.yaml` |
| **502 Bad Gateway** | Backend crash all'avvio | Render → Logs → cerca traceback |

### Logs in tempo reale
- **Render**: dashboard → servizio → tab **Logs**
- **Netlify**: dashboard → sito → tab **Deploys** → clic su deploy → log

---

## 🔄 Aggiornamenti futuri

Ogni `git push` su `main` triggera **automaticamente** un nuovo deploy:
- Render ribuilda il backend (~2-3 min)
- Netlify ribuilda il frontend (~30 s)

Per rigenerare i dati scraper Acea localmente prima di pushare:
```powershell
python -m backend.scraper
git add backend/data/results.json backend/data/pdfs/
git commit -m "Refresh data"
git push
```

---

## 💰 Costi

| Servizio | Piano Free | Piano consigliato |
|---|---|---|
| Render | 750h/mese + sleep dopo 15min | Starter $7/mese (no sleep, 512MB RAM) |
| Netlify | 100 GB banda/mese | gratis sufficiente |
| GitHub | 1 GB repo | gratis sufficiente |
| Gemini API | tier gratuito generoso | pay-as-you-go se superi |

Per traffico personale o demo, **tutto gratis** funziona bene.

---

## 📁 File chiave per il deploy

| File | Scopo |
|---|---|
| [render.yaml](render.yaml) | Blueprint Render (configurazione automatica) |
| [Procfile](Procfile) | Comando di avvio (fallback) |
| [runtime.txt](runtime.txt) | Versione Python |
| [requirements.txt](requirements.txt) | Dipendenze Python |
| [netlify.toml](netlify.toml) | Config Netlify (publish dir, headers, redirects) |
| [.env.example](.env.example) | Template variabili d'ambiente |

Buon deploy! 🌊
