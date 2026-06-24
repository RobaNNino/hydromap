# AcquaMap Business — Setup Supabase (Postgres + Auth)

Guida operativa per mettere in funzione AcquaMap Business con Supabase.

## 0. ⚠️ Rigenera la SECRET key (una tantum, urgente)
La vecchia `sb_secret_...` è stata esposta in chat: va revocata.
Dashboard Supabase → **Project Settings → API Keys → Secret keys → Roll/Revoke**, poi copia la **nuova** secret key. Non incollarla mai in chat o in file committati.

## 1. Crea le tabelle
Dashboard Supabase → **SQL Editor → New query** → incolla **tutto** il contenuto di
[`backend/sql/0001_business_schema.sql`](backend/sql/0001_business_schema.sql) → **Run**.
Crea `business_applications`, `business_profiles`, `business_water_info`, i trigger `updated_at` e le policy RLS.

## 2. Installa le dipendenze
```bash
pip install -r requirements.txt        # aggiunge supabase + PyJWT[crypto]
```

## 3. Configura `.env` (locale) — file già in `.gitignore`
```env
SUPABASE_URL=https://bzzbgtxlpwecqfydbguy.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_rPLQi9Swf8d4vzzYSocSQA_3JxZQ25N
SUPABASE_SECRET_KEY=<<< la SECRET key RIGENERATA al passo 0 >>>
SUPABASE_JWKS_URL=https://bzzbgtxlpwecqfydbguy.supabase.co/auth/v1/.well-known/jwks.json
BUSINESS_ADMIN_EMAILS=qtdguc@gmail.com
```

## 4. Verifica
```bash
python backend/check_supabase.py        # deve stampare "✓ tutto pronto"
```

## 5. Crea gli account
- **Admin**: Dashboard Supabase → **Authentication → Users → Add user** (la tua email).
  L'email deve essere in `BUSINESS_ADMIN_EMAILS`.
- **Titolari business**: si registrano da soli su `/acquamap/business/dashboard`
  con l'email indicata nella richiesta di iscrizione (claim automatico del profilo).

## 6. Deploy
- **Render** (backend): in *Environment* imposta `SUPABASE_SECRET_KEY` e `BUSINESS_ADMIN_EMAILS`
  (gli altri SUPABASE_* sono già in `render.yaml`). `SUPABASE_SECRET_KEY` resta `sync:false`.
- **Frontend** (`frontend/business/supabase-config.js`): contiene solo URL + publishable key (pubblici).
- **Supabase Auth → URL Configuration**: aggiungi il dominio del frontend (Netlify) agli
  *Redirect URLs* / *Site URL* per far funzionare login e conferma email.

## Architettura (sintesi)
- Backend **Flask** invariato; i dati business stanno su **Supabase Postgres**.
  Lo strato dati è in `backend/business.py` (`SupabaseRepo`), con fallback a store JSON
  locale (`JsonRepo`) quando Supabase non è configurato (utile in dev).
- Il server usa la **SECRET key** (bypassa RLS); l'autorizzazione è applicata in Flask
  dopo aver verificato il **JWT** dell'utente via **JWKS** (`backend/supa_auth.py`).
- RLS attiva come difesa in profondità: lettura pubblica solo dei profili `published`.
- Admin = email in `BUSINESS_ADMIN_EMAILS`. Titolare = `owner_id == auth.uid()`
  (collegato al primo login tramite `owner_email`).

## Flusso operativo
1. L'attività invia la richiesta su `/acquamap/business/apply` (pubblico).
2. L'admin la vede su `/admin/acquamap/business`, **approva** → crea un profilo in *bozza*.
3. L'admin completa dati/coordinate/acqua, imposta verifica/Expand e **pubblica**.
4. Il profilo appare su `/acquamap/business/<slug>` e come marker sulla mappa.
5. Il titolare accede alla dashboard (stessa email della richiesta) e aggiorna i propri dati.
