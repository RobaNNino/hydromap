"""
Client Supabase server-side per AcquaMap Business.

Usa la SECRET key (service_role): le query del backend BYPASSANO la RLS, perché
la logica di autorizzazione (admin vs titolare vs pubblico) è applicata in Flask
dopo aver verificato il JWT dell'utente (vedi supa_auth.py). La RLS resta come
backstop per l'accesso diretto con la publishable key.

Import "morbido": se il pacchetto `supabase` non è installato o le env non sono
configurate, `SUPABASE_ENABLED` resta False e il modulo business.py ripiega sullo
store JSON locale — l'app non si rompe mai in dev.
"""
from __future__ import annotations

import os
import threading

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")

try:
    from supabase import create_client, Client  # type: ignore
    _SDK_AVAILABLE = True
except Exception:  # pragma: no cover - pacchetto opzionale in dev
    create_client = None  # type: ignore
    Client = object  # type: ignore
    _SDK_AVAILABLE = False

# Abilitato solo se SDK presente E url+secret configurati.
SUPABASE_ENABLED = bool(_SDK_AVAILABLE and SUPABASE_URL and SUPABASE_SECRET_KEY)

_client = None
_client_lock = threading.Lock()


def get_client():
    """Ritorna un Client Supabase singleton (secret key). None se non configurato."""
    global _client
    if not SUPABASE_ENABLED:
        return None
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            _client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
    return _client


def status() -> dict:
    """Diagnostica leggera (per check_supabase.py / health)."""
    return {
        "sdk_installed": _SDK_AVAILABLE,
        "url_set": bool(SUPABASE_URL),
        "secret_key_set": bool(SUPABASE_SECRET_KEY),
        "enabled": SUPABASE_ENABLED,
    }
