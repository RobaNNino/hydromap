"""
Verifica la configurazione Supabase di AcquaMap Business.
Eseguire dopo aver: (1) rigenerato la SECRET key, (2) eseguito sql/0001_business_schema.sql,
(3) compilato .env.

    python backend/check_supabase.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Console Windows (cp1252) → forza UTF-8 per stampare i simboli ✓/✗ senza crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import supabase_client
import supa_auth


def main() -> int:
    ok = True
    print("== Supabase client ==")
    st = supabase_client.status()
    for k, v in st.items():
        print(f"  {k}: {v}")
    if not st["sdk_installed"]:
        print("  ✗ Pacchetto 'supabase' non installato → pip install -r requirements.txt")
        ok = False
    if not st["secret_key_set"]:
        print("  ✗ SUPABASE_SECRET_KEY mancante in .env (usa la chiave RIGENERATA)")
        ok = False

    if st["enabled"]:
        try:
            client = supabase_client.get_client()
            for table in ("business_applications", "business_profiles", "business_water_info"):
                res = client.table(table).select("id").limit(1).execute()
                print(f"  ✓ tabella '{table}' raggiungibile (rows visibili: {len(res.data or [])})")
        except Exception as e:
            print(f"  ✗ Query fallita: {e}")
            print("    → hai eseguito sql/0001_business_schema.sql nel SQL Editor?")
            ok = False

    print("== Supabase Auth (JWKS) ==")
    print(f"  jwks_url set: {bool(supa_auth.SUPABASE_JWKS_URL)}")
    print(f"  pyjwt installed: {supa_auth._JWT_AVAILABLE}")
    print(f"  auth_enabled: {supa_auth.AUTH_ENABLED}")
    print(f"  admin emails: {sorted(supa_auth.ADMIN_EMAILS) or '∅ (nessuna — imposta BUSINESS_ADMIN_EMAILS)'}")
    if supa_auth.AUTH_ENABLED:
        try:
            supa_auth._client().get_signing_keys()
            print("  ✓ JWKS scaricato correttamente")
        except Exception as e:
            print(f"  ✗ JWKS non raggiungibile: {e}")
            ok = False
    if not supa_auth.ADMIN_EMAILS:
        ok = False

    print()
    print("RISULTATO:", "✓ tutto pronto" if ok else "✗ configurazione incompleta (vedi sopra)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
