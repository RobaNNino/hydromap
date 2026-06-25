"""
AcquaMap Business — profili verificati di attività + "Expand Program".

Storage: Supabase Postgres quando configurato (SUPABASE_URL + SUPABASE_SECRET_KEY),
altrimenti ripiego su uno store JSON locale per lo sviluppo. La selezione è
trasparente: le rotte chiamano funzioni di modulo che delegano al repository attivo.

Auth: Supabase Auth (JWT verificati via JWKS, vedi supa_auth.py).
  - Admin  -> email del token in BUSINESS_ADMIN_EMAILS.
  - Titolare business -> profilo con owner_id == auth uid (claim-by-email al 1° login).
  - Pubblico/apply -> nessuna auth.

Sicurezza: validazione+sanitizzazione di ogni input; output pubblico ripulito da
campi privati (email referente, owner, application_id); slug unici; whitelist dei
campi modificabili dal business (no escalation di stato/verifica/premium).
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import abort, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

import supa_auth
from supabase_client import SUPABASE_ENABLED, get_client
from supabase_client import status as supabase_status

DATA_DIR = Path(__file__).parent / "data"

_LOCK = threading.RLock()

# ---------- enum / vocabolari ----------
CATEGORIES = ["bar", "ristorante", "hotel", "palestra", "centro_sportivo",
              "coworking", "ufficio", "scuola", "negozio", "altro"]
WATER_TYPES = ["rete", "filtrata", "microfiltrata", "frizzante", "naturale", "altro"]
FILTER_STATES = ["yes", "no", "undeclared"]
# Stati estesi (pipeline V1).
PROFILE_STATUSES = ["draft", "in_review", "changes_requested", "approved",
                    "published", "hidden", "suspended", "archived"]
VERIFICATION_STATES = ["not_verified", "verified", "business_verified"]
APPLICATION_STATUSES = ["pending", "accepted", "approved", "rejected"]
BADGE_KEYS = ["verified", "water_experience", "lab_quality", "business_premium"]
# Colonne "core" dell'applicazione: tutto il resto del payload finisce in `extra`.
_KNOWN_APP_FIELDS = {
    "business_name", "category", "contact_name", "contact_email", "contact_phone",
    "address", "city", "province", "region", "website", "instagram", "message",
    "wants_expand_program", "privacy_accepted", "status", "admin_notes", "profile_id", "extra",
}
WATER_PARAMS = ["ph", "hardness", "residue_fixed", "conductivity",
                "chlorine", "nitrates", "sodium", "calcium", "magnesium"]

MAX_TEXT = 2000
MAX_SHORT = 200

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")

# Nomi tabelle Supabase
T_APP = "business_applications"
T_PROF = "business_profiles"
T_WATER = "business_water_info"
_PROFILE_SELECT = "*, business_water_info(*)"


# ============================================================
# Utility / sanitizzazione
# ============================================================
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_str(value, maxlen: int = MAX_SHORT) -> str:
    if value is None:
        return ""
    s = str(value)
    s = "".join(ch for ch in s if ch in ("\n", "\t") or ord(ch) >= 32)
    return s.strip()[:maxlen]


def _clean_email(value) -> str:
    s = _clean_str(value, 254).lower()
    return s if _EMAIL_RE.match(s) else ""


def _clean_url(value) -> str:
    s = _clean_str(value, 500)
    if not s:
        return ""
    if not re.match(r"^https?://", s, re.I):
        s = "https://" + s
    return s if re.match(r"^https?://", s, re.I) else ""


def _clean_instagram(value) -> str:
    return _clean_str(value, 100).lstrip("@").strip()


MAX_IMG = 400_000  # cap data URL (~400KB) per loghi/immagini caricate


def _clean_image_url(value) -> str:
    """Accetta un URL http(s) oppure un data URL immagine (logo caricato e
    ridimensionato lato client). Tutto il resto viene scartato."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if s.startswith("data:image/"):
        return s[:MAX_IMG]
    return _clean_url(s)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "si", "sì")


def _as_float_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _category(value) -> str:
    v = _clean_str(value, 40).lower().replace(" ", "_")
    return v if v in CATEGORIES else "altro"


def slugify(name: str) -> str:
    norm = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_STRIP_RE.sub("-", norm.lower()).strip("-")
    return slug or "attivita"


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ============================================================
# Campi e validazione condivisi
# ============================================================
_BUSINESS_EDITABLE = ("description", "phone", "public_email", "website",
                      "instagram", "logo_url", "cover_image_url")
_ADMIN_EDITABLE = _BUSINESS_EDITABLE + (
    "business_name", "category", "address", "city", "province", "region",
    "country", "latitude", "longitude", "status", "verification_status",
    "is_expand_program", "is_premium", "contact_email", "owner_email", "badges",
)
# Campi che il titolare può modificare in onboarding (creazione profilo completo).
_ONBOARDING_EDITABLE = (
    "business_name", "category", "description", "address", "city", "province",
    "region", "country", "latitude", "longitude", "phone", "public_email",
    "website", "instagram", "logo_url", "cover_image_url",
)

# Campi mai esposti su endpoint pubblici.
_PRIVATE_PROFILE_FIELDS = (
    "contact_email", "owner_id", "owner_email", "application_id",
    "pin_hash", "onboarding_token", "account_token",
    "onboarding_expires", "account_expires",
)


def _default_water_info() -> dict:
    wi = {"water_type": [], "has_filter_system": "undeclared",
          "has_sparkling_water": False, "has_natural_water": False,
          "notes": "", "last_updated_at": None}
    for p in WATER_PARAMS:
        wi[p] = None
    return wi


def _build_water_info(payload: dict, base: dict | None = None) -> dict:
    wi = dict(base) if base else _default_water_info()
    if "water_type" in payload:
        raw = payload.get("water_type")
        if isinstance(raw, str):
            raw = [t for t in re.split(r"[,;]", raw) if t.strip()]
        types = [_clean_str(t, 40).lower() for t in (raw or [])]
        wi["water_type"] = [t for t in types if t in WATER_TYPES]
    if "has_filter_system" in payload:
        v = _clean_str(payload.get("has_filter_system"), 20).lower()
        wi["has_filter_system"] = v if v in FILTER_STATES else "undeclared"
    if "has_sparkling_water" in payload:
        wi["has_sparkling_water"] = _as_bool(payload.get("has_sparkling_water"))
    if "has_natural_water" in payload:
        wi["has_natural_water"] = _as_bool(payload.get("has_natural_water"))
    if "notes" in payload:
        wi["notes"] = _clean_str(payload.get("notes"), MAX_TEXT)
    for p in WATER_PARAMS:
        if p in payload:
            wi[p] = _as_float_or_none(payload.get(p))
    wi["last_updated_at"] = _now()
    return wi


def _clean_profile_fields(patch: dict, allowed: tuple) -> dict:
    """Ritorna un dict {colonna: valore pulito} per i soli campi ammessi presenti."""
    out: dict = {}
    for key in allowed:
        if key not in patch:
            continue
        val = patch[key]
        if key == "description":
            out[key] = _clean_str(val, MAX_TEXT)
        elif key in ("public_email", "contact_email", "owner_email"):
            out[key] = _clean_email(val)
        elif key == "website":
            out[key] = _clean_url(val)
        elif key in ("logo_url", "cover_image_url"):
            out[key] = _clean_image_url(val)
        elif key == "instagram":
            out[key] = _clean_instagram(val)
        elif key == "category":
            out[key] = _category(val)
        elif key == "status":
            v = _clean_str(val, 20).lower()
            if v in PROFILE_STATUSES:
                out[key] = v
        elif key == "verification_status":
            v = _clean_str(val, 30).lower()
            if v in VERIFICATION_STATES:
                out[key] = v
        elif key in ("is_expand_program", "is_premium"):
            out[key] = _as_bool(val)
        elif key in ("latitude", "longitude"):
            out[key] = _as_float_or_none(val)
        elif key == "badges":
            vals = val if isinstance(val, list) else []
            out[key] = [b for b in (_clean_str(x, 40) for x in vals) if b in BADGE_KEYS]
        else:
            out[key] = _clean_str(val, MAX_SHORT)
    return out


def _clean_extra(extra: dict) -> dict:
    """Sanitizza ricorsivamente il blob `extra` (jsonb): stringhe ripulite,
    bool/numeri/liste preservati, profondità limitata."""
    def clean(v, depth=0):
        if depth > 4:
            return None
        if isinstance(v, str):
            return _clean_str(v, MAX_TEXT)
        if isinstance(v, bool) or v is None or isinstance(v, (int, float)):
            return v
        if isinstance(v, list):
            return [clean(x, depth + 1) for x in v[:60]]
        if isinstance(v, dict):
            return {str(k)[:60]: clean(val, depth + 1) for k, val in list(v.items())[:80]}
        return None
    return clean(extra or {}, 0) or {}


def _initial_profile_columns(fields: dict, slug: str) -> dict:
    name = _clean_str(fields.get("business_name")) or "Attività"
    cols = {
        "slug": slug,
        "business_name": name,
        "category": _category(fields.get("category")),
        "description": _clean_str(fields.get("description"), MAX_TEXT),
        "address": _clean_str(fields.get("address")),
        "city": _clean_str(fields.get("city")),
        "province": _clean_str(fields.get("province"), 60),
        "region": _clean_str(fields.get("region"), 60),
        "country": _clean_str(fields.get("country"), 60) or "Italia",
        "latitude": _as_float_or_none(fields.get("latitude")),
        "longitude": _as_float_or_none(fields.get("longitude")),
        "phone": _clean_str(fields.get("phone"), 40),
        "public_email": _clean_email(fields.get("public_email")),
        "website": _clean_url(fields.get("website")),
        "instagram": _clean_instagram(fields.get("instagram")),
        "logo_url": _clean_image_url(fields.get("logo_url")),
        "cover_image_url": _clean_image_url(fields.get("cover_image_url")),
        "status": "draft",
        "verification_status": "not_verified",
        "is_expand_program": _as_bool(fields.get("is_expand_program")),
        "is_premium": False,
        "owner_email": _clean_email(fields.get("owner_email") or fields.get("contact_email")),
        "contact_email": _clean_email(fields.get("contact_email")),
        "application_id": fields.get("application_id"),
    }
    return cols


def _validate_application(payload: dict) -> tuple[dict, dict]:
    business_name = _clean_str(payload.get("business_name"))
    contact_name = _clean_str(payload.get("contact_name"))
    contact_email = _clean_email(payload.get("contact_email"))
    privacy = _as_bool(payload.get("privacy_accepted"))
    errors = {}
    if not business_name:
        errors["business_name"] = "Nome attività obbligatorio."
    if not contact_name:
        errors["contact_name"] = "Nome referente obbligatorio."
    if not contact_email:
        errors["contact_email"] = "Email referente non valida."
    if not privacy:
        errors["privacy_accepted"] = "È necessario accettare la privacy."
    if errors:
        return {}, errors
    row = {
        "business_name": business_name,
        "category": _category(payload.get("category")),
        "contact_name": contact_name,
        "contact_email": contact_email,
        "contact_phone": _clean_str(payload.get("contact_phone"), 40),
        "address": _clean_str(payload.get("address")),
        "city": _clean_str(payload.get("city")),
        "province": _clean_str(payload.get("province"), 60),
        "region": _clean_str(payload.get("region"), 60),
        "website": _clean_url(payload.get("website")),
        "instagram": _clean_instagram(payload.get("instagram")),
        "message": _clean_str(payload.get("message") or payload.get("goal_why"), MAX_TEXT),
        "wants_expand_program": _as_bool(payload.get("wants_expand_program")),
        "privacy_accepted": True,
        "status": "pending",
        "admin_notes": "",
        "profile_id": None,
    }
    # Tutti i campi non-core della candidatura avanzata finiscono in extra (jsonb).
    extra = {k: v for k, v in (payload or {}).items() if k not in _KNOWN_APP_FIELDS}
    row["extra"] = _clean_extra(extra)
    return row, {}


# ============================================================
# Serializzazione
# ============================================================
def _public_profile(p: dict) -> dict:
    return {k: v for k, v in p.items() if k not in _PRIVATE_PROFILE_FIELDS}


def _matches_filters(p: dict, f: dict) -> bool:
    if f.get("category") and p.get("category") != f["category"]:
        return False
    if f.get("expand") and not p.get("is_expand_program"):
        return False
    if f.get("verified") and p.get("verification_status") == "not_verified":
        return False
    wi = p.get("water_info") or {}
    if f.get("water_type") and f["water_type"] not in set(wi.get("water_type") or []):
        return False
    if f.get("filtered") and wi.get("has_filter_system") != "yes":
        return False
    if f.get("sparkling") and not wi.get("has_sparkling_water"):
        return False
    return True


def _geojson(profiles: list[dict]) -> dict:
    feats = []
    for p in profiles:
        lat, lng = p.get("latitude"), p.get("longitude")
        if lat is None or lng is None:
            continue
        wi = p.get("water_info") or {}
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "id": p.get("id"), "slug": p.get("slug"),
                "business_name": p.get("business_name"), "category": p.get("category"),
                "city": p.get("city"),
                "address": p.get("address"),
                "logo_url": p.get("logo_url") or "",
                "verification_status": p.get("verification_status"),
                "is_expand_program": p.get("is_expand_program"), "is_premium": p.get("is_premium"),
                "water_type": wi.get("water_type") or [], "has_filter_system": wi.get("has_filter_system"),
            },
        })
    return {"type": "FeatureCollection", "features": feats}


# ============================================================
# Repository: Supabase Postgres
# ============================================================
class SupabaseRepo:
    def _c(self):
        return get_client()

    def _flatten(self, row):
        if not row:
            return row
        water = row.pop("business_water_info", None)
        if isinstance(water, list):
            water = water[0] if water else None
        wi = _default_water_info()
        if water:
            for k in list(wi.keys()):
                if k in water and water[k] is not None:
                    wi[k] = water[k]
            wi["water_type"] = water.get("water_type") or []
        row["water_info"] = wi
        return row

    def _slug_exists(self, slug, exclude_id=None):
        q = self._c().table(T_PROF).select("id").eq("slug", slug)
        res = q.execute()
        rows = res.data or []
        if exclude_id:
            rows = [r for r in rows if r.get("id") != exclude_id]
        return bool(rows)

    def _unique_slug(self, base):
        slug, i = base, 2
        while self._slug_exists(slug):
            slug = f"{base}-{i}"
            i += 1
        return slug

    # ----- applications -----
    def create_application(self, row):
        res = self._c().table(T_APP).insert(row).execute()
        return (res.data or [None])[0]

    def list_applications(self, status=None):
        q = self._c().table(T_APP).select("*").order("created_at", desc=True)
        if status:
            q = q.eq("status", status)
        return q.execute().data or []

    def get_application(self, app_id):
        res = self._c().table(T_APP).select("*").eq("id", app_id).execute()
        return (res.data or [None])[0]

    def update_application(self, app_id, patch):
        upd = {}
        if "status" in patch:
            v = _clean_str(patch["status"], 20).lower()
            if v in APPLICATION_STATUSES:
                upd["status"] = v
        if "admin_notes" in patch:
            upd["admin_notes"] = _clean_str(patch["admin_notes"], MAX_TEXT)
        if "profile_id" in patch:
            upd["profile_id"] = patch["profile_id"]
        if not upd:
            return self.get_application(app_id)
        res = self._c().table(T_APP).update(upd).eq("id", app_id).execute()
        return (res.data or [None])[0]

    # ----- profiles -----
    def _insert_profile(self, fields):
        base = slugify(_clean_str(fields.get("slug"), 120)) if fields.get("slug") else slugify(fields.get("business_name") or "")
        slug = self._unique_slug(base)
        cols = _initial_profile_columns(fields, slug)
        cols.update(_clean_profile_fields(fields, _ADMIN_EDITABLE))
        res = self._c().table(T_PROF).insert(cols).execute()
        prof = (res.data or [None])[0]
        if not prof:
            return None
        # crea la riga acqua collegata
        wi = _build_water_info(fields, _default_water_info())
        self._upsert_water(prof["id"], wi)
        return self.get_profile(prof["id"])

    def _upsert_water(self, profile_id, wi):
        row = {"business_profile_id": profile_id}
        for k in ["water_type", "has_filter_system", "has_sparkling_water",
                  "has_natural_water", "notes", "last_updated_at"] + WATER_PARAMS:
            row[k] = wi.get(k)
        self._c().table(T_WATER).upsert(row, on_conflict="business_profile_id").execute()

    def list_profiles(self):
        res = self._c().table(T_PROF).select(_PROFILE_SELECT).order("created_at", desc=True).execute()
        return [self._flatten(r) for r in (res.data or [])]

    def get_profile(self, profile_id):
        res = self._c().table(T_PROF).select(_PROFILE_SELECT).eq("id", profile_id).execute()
        rows = res.data or []
        return self._flatten(rows[0]) if rows else None

    def create_profile(self, fields):
        return self._insert_profile(fields)

    def update_profile(self, profile_id, patch, allowed):
        upd = _clean_profile_fields(patch, allowed)
        if "slug" in patch and allowed is _ADMIN_EDITABLE and patch["slug"]:
            ns = slugify(patch["slug"])
            if not self._slug_exists(ns, exclude_id=profile_id):
                upd["slug"] = ns
        if upd:
            self._c().table(T_PROF).update(upd).eq("id", profile_id).execute()
        return self.get_profile(profile_id)

    def delete_profile(self, profile_id):
        self._c().table(T_PROF).delete().eq("id", profile_id).execute()
        return True

    def set_water_info(self, profile_id, payload):
        wi = _build_water_info(payload, _default_water_info())
        self._upsert_water(profile_id, wi)
        return self.get_profile(profile_id)

    def find_owned(self, user_id, email):
        res = self._c().table(T_PROF).select(_PROFILE_SELECT).eq("owner_id", user_id).execute()
        rows = res.data or []
        if rows:
            return self._flatten(rows[0])
        email = (email or "").lower()
        if not email:
            return None
        res = self._c().table(T_PROF).select(_PROFILE_SELECT).is_("owner_id", "null").ilike("owner_email", email).execute()
        rows = res.data or []
        if not rows:
            return None
        prof = rows[0]
        self._c().table(T_PROF).update({"owner_id": user_id}).eq("id", prof["id"]).execute()
        return self.get_profile(prof["id"])

    # ----- V1: token onboarding / account, PIN, extra -----
    def _get_by_token(self, column, token):
        if not token:
            return None
        res = self._c().table(T_PROF).select(_PROFILE_SELECT).eq(column, token).execute()
        rows = res.data or []
        return self._flatten(rows[0]) if rows else None

    def set_token(self, profile_id, column, token, expires_iso):
        self._c().table(T_PROF).update({
            column: token, column.replace("_token", "_expires"): expires_iso,
        }).eq("id", profile_id).execute()

    def get_by_onboarding_token(self, token):
        return self._get_by_token("onboarding_token", token)

    def get_by_account_token(self, token):
        return self._get_by_token("account_token", token)

    def update_onboarding(self, profile_id, fields, extra):
        upd = _clean_profile_fields(fields, _ONBOARDING_EDITABLE)
        if extra is not None:
            cur = self.get_profile(profile_id) or {}
            merged = {**(cur.get("extra") or {}), **_clean_extra(extra)}
            upd["extra"] = merged
        if "water_type" in (extra or {}) or "water" in (extra or {}):
            pass  # le info acqua avanzate restano in extra per la V1
        if upd:
            self._c().table(T_PROF).update(upd).eq("id", profile_id).execute()
        return self.get_profile(profile_id)

    def submit_onboarding(self, profile_id):
        self._c().table(T_PROF).update({"status": "in_review", "submitted_at": _now()}).eq("id", profile_id).execute()
        return self.get_profile(profile_id)

    def complete_account(self, profile_id, user_id, pin_hash):
        self._c().table(T_PROF).update({
            "owner_id": user_id, "account_created": True, "pin_hash": pin_hash,
            "account_token": None,
        }).eq("id", profile_id).execute()
        return self.get_profile(profile_id)

    def set_pin(self, profile_id, pin_hash):
        self._c().table(T_PROF).update({"pin_hash": pin_hash}).eq("id", profile_id).execute()
        return self.get_profile(profile_id)


_repo = SupabaseRepo()


# ============================================================
# API di modulo (usate dalle rotte) — delega al repository attivo
# ============================================================
def create_application(payload: dict) -> dict:
    row, errors = _validate_application(payload)
    if errors:
        return {"ok": False, "errors": errors}
    app_obj = _repo.create_application(row)
    try:
        from mailer import send_apply_received
        send_apply_received(app_obj)
    except Exception:
        pass
    try:
        import business_v2
        business_v2.notify("admin", None, "new_application",
                           "Nuova richiesta", f"{app_obj.get('business_name')} — {app_obj.get('city') or ''}")
        business_v2.audit(None, app_obj.get("contact_email"), "application_submitted", app_obj.get("business_name") or "")
    except Exception:
        pass
    return {"ok": True, "application": app_obj}


def list_applications(status=None):
    return _repo.list_applications(status)


def get_application(app_id):
    return _repo.get_application(app_id)


def update_application(app_id, patch):
    return _repo.update_application(app_id, patch)


def reject_application(app_id, notes=""):
    return _repo.update_application(app_id, {"status": "rejected", "admin_notes": _clean_str(notes, MAX_TEXT)})


def approve_application(app_id, extra=None):
    extra = extra or {}
    app_obj = _repo.get_application(app_id)
    if not app_obj:
        return {"ok": False, "error": "application_not_found"}
    if app_obj.get("profile_id"):
        existing = _repo.get_profile(app_obj["profile_id"])
        if existing:
            return {"ok": True, "profile": existing, "already": True}
    fields = {
        "business_name": app_obj.get("business_name"),
        "category": app_obj.get("category"),
        "address": app_obj.get("address"),
        "city": app_obj.get("city"),
        "province": app_obj.get("province"),
        "region": app_obj.get("region"),
        "website": app_obj.get("website"),
        "instagram": app_obj.get("instagram"),
        "phone": app_obj.get("contact_phone"),
        "contact_email": app_obj.get("contact_email"),
        "owner_email": app_obj.get("contact_email"),
        "is_expand_program": app_obj.get("wants_expand_program"),
        "application_id": app_obj.get("id"),
        **extra,
    }
    profile = _repo.create_profile(fields)
    _repo.update_application(app_id, {"status": "approved", "profile_id": profile["id"]})
    return {"ok": True, "profile": profile}


def list_profiles():
    return _repo.list_profiles()


def get_profile(profile_id):
    return _repo.get_profile(profile_id)


def create_profile(fields):
    return _repo.create_profile(fields)


def update_profile(profile_id, patch, admin=True):
    return _repo.update_profile(profile_id, patch, _ADMIN_EDITABLE if admin else _BUSINESS_EDITABLE)


def delete_profile(profile_id):
    return _repo.delete_profile(profile_id)


def set_water_info(profile_id, payload):
    return _repo.set_water_info(profile_id, payload)


def list_public_profiles(filters=None):
    filters = filters or {}
    profs = [p for p in _repo.list_profiles() if p.get("status") == "published"]
    out = [_public_profile(p) for p in profs if _matches_filters(p, filters)]
    return sorted(out, key=lambda p: (p.get("business_name") or "").lower())


def get_public_profile_by_slug(slug):
    slug = slugify(slug)
    for p in _repo.list_profiles():
        if p.get("slug") == slug and p.get("status") == "published":
            return _public_profile(p)
    return None


def public_profiles_geojson(filters=None):
    return _geojson(list_public_profiles(filters))


def get_profile_for_user(user):
    return _repo.find_owned(user["id"], user.get("email"))


# ============================================================
# V1: token onboarding/account, PIN, badge
# ============================================================
def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _expiry(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def _token_valid(profile: dict, kind: str) -> bool:
    exp = profile.get(f"{kind}_expires")
    if not exp:
        return True
    try:
        return datetime.fromisoformat(exp) >= datetime.now(timezone.utc)
    except Exception:
        return True


def generate_onboarding_link(profile_id: str) -> dict | None:
    if not _repo.get_profile(profile_id):
        return None
    token = _new_token()
    _repo.set_token(profile_id, "onboarding_token", token, _expiry(30))
    return {"token": token}


def generate_account_link(profile_id: str) -> dict | None:
    if not _repo.get_profile(profile_id):
        return None
    token = _new_token()
    _repo.set_token(profile_id, "account_token", token, _expiry(14))
    return {"token": token}


def get_onboarding_profile(token: str) -> dict | None:
    p = _repo.get_by_onboarding_token(token)
    if not p or not _token_valid(p, "onboarding"):
        return None
    return _strip_tokens(p)


def update_onboarding_profile(token: str, payload: dict) -> dict | None:
    p = _repo.get_by_onboarding_token(token)
    if not p or not _token_valid(p, "onboarding"):
        return None
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    updated = _repo.update_onboarding(p["id"], payload, extra)
    return _strip_tokens(updated or {})


def submit_onboarding_profile(token: str) -> dict | None:
    p = _repo.get_by_onboarding_token(token)
    if not p or not _token_valid(p, "onboarding"):
        return None
    updated = _repo.submit_onboarding(p["id"])
    try:
        from mailer import send_profile_received
        send_profile_received(updated or p)
    except Exception:
        pass
    try:
        import business_v2
        business_v2.notify("admin", p["id"], "profile_submitted",
                           "Profilo da revisionare", f"{p.get('business_name')} ha inviato il profilo.")
        business_v2.audit(p["id"], p.get("owner_email"), "profile_submitted", "")
    except Exception:
        pass
    return _strip_tokens(updated or {})


def get_account_context(token: str) -> dict | None:
    p = _repo.get_by_account_token(token)
    if not p or not _token_valid(p, "account"):
        return None
    return {"business_name": p.get("business_name"), "owner_email": p.get("owner_email")}


def complete_account(token: str, user: dict, pin: str) -> dict:
    p = _repo.get_by_account_token(token)
    if not p or not _token_valid(p, "account"):
        return {"ok": False, "error": "token_non_valido"}
    if (p.get("owner_email") or "").lower() != (user.get("email") or "").lower():
        return {"ok": False, "error": "email_non_corrisponde"}
    if not re.fullmatch(r"\d{4,6}", pin or ""):
        return {"ok": False, "error": "pin_non_valido"}
    _repo.complete_account(p["id"], user["id"], generate_password_hash(pin))
    return {"ok": True}


def set_owner_pin(user: dict, pin: str) -> dict:
    if not re.fullmatch(r"\d{4,6}", pin or ""):
        return {"ok": False, "error": "pin_non_valido"}
    p = get_profile_for_user(user)
    if not p:
        return {"ok": False, "error": "nessun_profilo"}
    _repo.set_pin(p["id"], generate_password_hash(pin))
    return {"ok": True}


def verify_owner_pin(user: dict, pin: str) -> bool:
    p = get_profile_for_user(user)
    return bool(p and p.get("pin_hash") and check_password_hash(p["pin_hash"], pin or ""))


def _strip_tokens(p: dict) -> dict:
    return {k: v for k, v in (p or {}).items()
            if k not in ("pin_hash", "onboarding_token", "account_token")}


# ============================================================
# Geocoding (OSM/Nominatim) con cache su disco — usato dall'admin per
# posizionare i locali per via e civico senza inserire coordinate a mano.
# ============================================================
_GEOCACHE_FILE = DATA_DIR / "business_geocache.json"
_geocache_lock = threading.Lock()


def _load_geocache() -> dict:
    try:
        return json.loads(_GEOCACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_geocache(d: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _GEOCACHE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_GEOCACHE_FILE)
    except Exception:
        pass


def geocode(q: str) -> list[dict]:
    """Indirizzo (via, civico, città) -> lista di candidati {display_name, lat, lon}."""
    key = " ".join(q.strip().lower().split())
    with _geocache_lock:
        cache = _load_geocache()
        if key in cache:
            return cache[key]
    items: list[dict] = []
    try:
        import requests
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"format": "json", "q": q, "countrycodes": "it",
                    "limit": 6, "addressdetails": 1},
            headers={"User-Agent": "AcquaMap/1.0 (business geocoder)"},
            timeout=10,
        )
        r.raise_for_status()
        for it in r.json():
            try:
                items.append({
                    "display_name": it.get("display_name"),
                    "lat": float(it["lat"]),
                    "lon": float(it["lon"]),
                    "type": it.get("type"),
                })
            except (KeyError, TypeError, ValueError):
                continue
    except Exception:
        items = []
    with _geocache_lock:
        cache = _load_geocache()
        cache[key] = items
        _save_geocache(cache)
    return items


# ============================================================
# Rotte Flask
# ============================================================
def _json_body() -> dict:
    return request.get_json(force=True, silent=True) or {}


def _strip_for_owner(p: dict) -> dict:
    # Il titolare vede i propri dati (incl. contact_email); nascondiamo solo owner_id.
    return {k: v for k, v in p.items() if k != "owner_id"}


def register_business_routes(app) -> None:
    # Guardia: gli endpoint business richiedono Supabase configurato.
    # /api/business/config resta accessibile per diagnosticare la configurazione.
    @app.before_request
    def _guard_supabase():
        p = request.path
        if p == "/api/business/config":
            return None
        if (p.startswith("/api/business") or p.startswith("/api/admin/business")) and not SUPABASE_ENABLED:
            return jsonify({"error": "Supabase non configurato sul server."}), 503
        return None

    # ---------- Pubblici ----------
    @app.get("/api/business")
    def api_business_list():
        f = {
            "category": (request.args.get("category") or "").strip().lower() or None,
            "verified": request.args.get("verified") in ("1", "true"),
            "expand": request.args.get("expand") in ("1", "true"),
            "filtered": request.args.get("filtered") in ("1", "true"),
            "sparkling": request.args.get("sparkling") in ("1", "true"),
            "water_type": (request.args.get("water_type") or "").strip().lower() or None,
        }
        items = list_public_profiles(f)
        return jsonify({"items": items, "count": len(items)})

    @app.get("/api/business/map")
    def api_business_map():
        return jsonify(public_profiles_geojson())

    @app.get("/api/business/<slug>")
    def api_business_detail(slug):
        p = get_public_profile_by_slug(slug)
        if not p:
            abort(404, description="Profilo business non trovato o non pubblicato.")
        return jsonify(p)

    @app.post("/api/business/apply")
    def api_business_apply():
        result = create_application(_json_body())
        if not result.get("ok"):
            return jsonify({"ok": False, "errors": result.get("errors", {})}), 400
        return jsonify({
            "ok": True,
            "message": "Richiesta inviata. Ti contatteremo dopo la verifica.",
            "application_id": result["application"]["id"],
        }), 201

    @app.get("/api/business/config")
    def api_business_config():
        return jsonify({
            "categories": CATEGORIES, "water_types": WATER_TYPES,
            "filter_states": FILTER_STATES, "verification_states": VERIFICATION_STATES,
            "profile_statuses": PROFILE_STATUSES, "water_params": WATER_PARAMS,
            "supabase": supabase_status(),
            "auth": {
                "jwt_enabled": supa_auth.AUTH_ENABLED,
                "supabase_enabled": SUPABASE_ENABLED,
            },
        })

    # ---------- Geocoding (indirizzo -> coordinate) per il posizionamento admin ----------
    @app.get("/api/business/geocode")
    def api_business_geocode():
        supa_auth.require_admin()
        q = (request.args.get("q") or "").strip()
        if len(q) < 3:
            return jsonify({"items": []})
        return jsonify({"items": geocode(q)})

    # ---------- Onboarding profilo (token-based, pubblico) ----------
    @app.get("/api/business/onboarding/<token>")
    def api_onboarding_get(token):
        p = get_onboarding_profile(token)
        if not p:
            abort(404, description="Link onboarding non valido o scaduto.")
        return jsonify(p)

    @app.patch("/api/business/onboarding/<token>")
    def api_onboarding_patch(token):
        p = update_onboarding_profile(token, _json_body())
        if not p:
            abort(404, description="Link onboarding non valido o scaduto.")
        return jsonify(p)

    @app.post("/api/business/onboarding/<token>/submit")
    def api_onboarding_submit(token):
        p = submit_onboarding_profile(token)
        if not p:
            abort(404, description="Link onboarding non valido o scaduto.")
        return jsonify({"ok": True, "profile": p})

    # ---------- Creazione account (token-based) ----------
    @app.get("/api/business/account/<token>")
    def api_account_get(token):
        ctx = get_account_context(token)
        if not ctx:
            abort(404, description="Link non valido o scaduto.")
        return jsonify(ctx)

    @app.post("/api/business/account/<token>/complete")
    def api_account_complete(token):
        user = supa_auth.require_user()
        res = complete_account(token, user, _json_body().get("pin", ""))
        if not res.get("ok"):
            abort(400, description=res.get("error", "errore"))
        return jsonify({"ok": True})

    # ---------- Dashboard business (Supabase Auth) ----------
    @app.get("/api/business/me")
    def api_business_me():
        user = supa_auth.require_user()
        p = get_profile_for_user(user)
        if not p:
            abort(404, description="Nessuna attività associata a questo account.")
        return jsonify(_strip_for_owner(p))

    @app.post("/api/business/me/pin")
    def api_business_me_pin():
        user = supa_auth.require_user()
        res = set_owner_pin(user, _json_body().get("pin", ""))
        if not res.get("ok"):
            abort(400, description=res.get("error", "errore"))
        return jsonify({"ok": True})

    @app.patch("/api/business/me")
    def api_business_me_update():
        user = supa_auth.require_user()
        p = get_profile_for_user(user)
        if not p:
            abort(404, description="Nessuna attività associata a questo account.")
        import business_v2
        body = _json_body()
        # I campi sensibili (telefono/email pubblica) NON vanno online subito:
        # diventano "modifiche in attesa" da approvare in admin.
        direct, sensitive = business_v2.split_business_edit(p, body, _BUSINESS_EDITABLE)
        updated = update_profile(p["id"], direct, admin=False) if direct else p
        pending = []
        for field, new in sensitive.items():
            try:
                cleaned = _clean_profile_fields({field: new}, _BUSINESS_EDITABLE).get(field, new)
                business_v2.create_pending_change(p["id"], field, p.get(field), cleaned, user.get("email", ""))
                pending.append(field)
            except Exception:
                pass
        out = _strip_for_owner(updated or {})
        out["pending_changes"] = pending
        return jsonify(out)

    @app.patch("/api/business/me/water-info")
    def api_business_me_water():
        user = supa_auth.require_user()
        p = get_profile_for_user(user)
        if not p:
            abort(404, description="Nessuna attività associata a questo account.")
        updated = set_water_info(p["id"], _json_body())
        return jsonify(_strip_for_owner(updated or {}))

    # ---------- Admin (Supabase Auth + allowlist email) ----------
    @app.get("/api/admin/business/applications")
    def api_admin_apps():
        supa_auth.require_admin()
        status = (request.args.get("status") or "").strip().lower() or None
        return jsonify({"items": list_applications(status)})

    @app.get("/api/admin/business/applications/<app_id>")
    def api_admin_app_detail(app_id):
        supa_auth.require_admin()
        a = get_application(app_id)
        if not a:
            abort(404)
        return jsonify(a)

    @app.patch("/api/admin/business/applications/<app_id>")
    def api_admin_app_update(app_id):
        supa_auth.require_admin()
        a = update_application(app_id, _json_body())
        if not a:
            abort(404)
        return jsonify(a)

    @app.post("/api/admin/business/applications/<app_id>/approve")
    def api_admin_app_approve(app_id):
        supa_auth.require_admin()
        result = approve_application(app_id, _json_body())
        if not result.get("ok"):
            abort(404, description=result.get("error", "errore"))
        return jsonify(result)

    @app.post("/api/admin/business/applications/<app_id>/reject")
    def api_admin_app_reject(app_id):
        supa_auth.require_admin()
        a = reject_application(app_id, _json_body().get("admin_notes", ""))
        if not a:
            abort(404)
        return jsonify(a)

    @app.get("/api/admin/business/profiles")
    def api_admin_profiles():
        supa_auth.require_admin()
        return jsonify({"items": list_profiles()})

    @app.get("/api/admin/business/profiles/<profile_id>")
    def api_admin_profile_detail(profile_id):
        supa_auth.require_admin()
        p = get_profile(profile_id)
        if not p:
            abort(404)
        return jsonify(p)

    @app.post("/api/admin/business/profiles")
    def api_admin_profile_create():
        supa_auth.require_admin()
        return jsonify(create_profile(_json_body())), 201

    @app.patch("/api/admin/business/profiles/<profile_id>")
    def api_admin_profile_update(profile_id):
        supa_auth.require_admin()
        body = _json_body()
        p = update_profile(profile_id, body, admin=True)
        if not p:
            abort(404)
        if any(k in body for k in (["water_type", "has_filter_system", "has_sparkling_water",
               "has_natural_water", "water_notes"] + WATER_PARAMS)):
            wi_payload = dict(body)
            if "water_notes" in body:
                wi_payload["notes"] = body["water_notes"]
            p = set_water_info(profile_id, wi_payload)
        if body.get("status") == "published":
            try:
                from mailer import send_published
                send_published(p)
            except Exception:
                pass
            try:
                import business_v2
                business_v2.notify("business", profile_id, "published", "Profilo pubblicato",
                                   "Il tuo profilo è ora online su AcquaMap.")
                business_v2.audit(profile_id, "admin", "profile_published", "")
            except Exception:
                pass
        return jsonify(p)

    @app.delete("/api/admin/business/profiles/<profile_id>")
    def api_admin_profile_delete(profile_id):
        supa_auth.require_admin()
        if not delete_profile(profile_id):
            abort(404)
        return jsonify({"ok": True})

    @app.post("/api/admin/business/profiles/<profile_id>/onboarding-link")
    def api_admin_onboarding_link(profile_id):
        supa_auth.require_admin()
        res = generate_onboarding_link(profile_id)
        if not res:
            abort(404)
        try:
            from mailer import send_onboarding_link
            p = get_profile(profile_id)
            send_onboarding_link(p, res["token"])
        except Exception:
            pass
        return jsonify(res)

    @app.post("/api/admin/business/profiles/<profile_id>/account-link")
    def api_admin_account_link(profile_id):
        supa_auth.require_admin()
        res = generate_account_link(profile_id)
        if not res:
            abort(404)
        try:
            from mailer import send_account_link
            p = get_profile(profile_id)
            send_account_link(p, res["token"])
        except Exception:
            pass
        return jsonify(res)
