"""
Verifica dei JWT di Supabase Auth (lato Flask) tramite JWKS.

Gli utenti (titolari business e admin) effettuano il login con Supabase Auth nel
frontend; ogni richiesta protetta porta l'header `Authorization: Bearer <jwt>`.
Qui il token viene verificato localmente con le chiavi pubbliche JWKS (nessuna
chiamata di rete per richiesta: PyJWKClient mette in cache le chiavi).

Ruolo admin: l'email del token deve essere nell'allowlist BUSINESS_ADMIN_EMAILS.
"""
from __future__ import annotations

import os

from flask import abort, request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_JWKS_URL = os.environ.get("SUPABASE_JWKS_URL", "")
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("BUSINESS_ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# Algoritmi asimmetrici usati dalle signing keys Supabase.
_ALGORITHMS = ["ES256", "RS256", "EdDSA"]

try:
    import jwt  # PyJWT
    from jwt import PyJWKClient
    _JWT_AVAILABLE = True
except Exception:  # pragma: no cover
    jwt = None  # type: ignore
    PyJWKClient = None  # type: ignore
    _JWT_AVAILABLE = False

AUTH_ENABLED = bool(_JWT_AVAILABLE and SUPABASE_JWKS_URL)

_jwk_client = None


def _client():
    global _jwk_client
    if not AUTH_ENABLED:
        return None
    if _jwk_client is None:
        # lifespan: cache delle chiavi per ridurre i fetch del JWKS.
        _jwk_client = PyJWKClient(SUPABASE_JWKS_URL, lifespan=3600)
    return _jwk_client


def verify_token(token: str) -> dict | None:
    """Verifica firma + scadenza + audience. Ritorna i claims o None se invalido."""
    if not token or not AUTH_ENABLED:
        return None
    try:
        signing_key = _client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS,
            audience="authenticated",
            issuer=(f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else None),
            options={"verify_aud": True, "verify_iss": bool(SUPABASE_URL)},
        )
        return claims
    except Exception:
        return None


def bearer_token() -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def current_user() -> dict | None:
    """Utente autenticato dalla richiesta corrente, o None."""
    claims = verify_token(bearer_token())
    if not claims:
        return None
    return {
        "id": claims.get("sub"),
        "email": (claims.get("email") or "").lower(),
        "role": claims.get("role"),
        "claims": claims,
    }


def is_admin(user: dict | None) -> bool:
    return bool(user and user.get("email") and user["email"] in ADMIN_EMAILS)


def require_user() -> dict:
    if not AUTH_ENABLED:
        abort(503, description="Supabase Auth non configurato (SUPABASE_JWKS_URL).")
    user = current_user()
    if not user:
        abort(401, description="Autenticazione richiesta o token non valido.")
    return user


def require_admin() -> dict:
    user = require_user()
    if not is_admin(user):
        abort(403, description="Permessi amministratore richiesti.")
    return user
