"""
AcquaMap Business — Versione 2 (Professionale).

Analytics (eventi grezzi + aggregato giornaliero), notifiche, modifiche in attesa,
messaggi admin<->business, audit log, anti-duplicati.

Tutto su Supabase (secret key, server-side). Le rotte sono registrate da
`register_v2_routes(app)`. Le funzioni richiamano business.py via import lazy per
evitare cicli di import.
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta, timezone

from flask import abort, jsonify, request

import supa_auth
from supabase_client import SUPABASE_ENABLED, get_client

# Campi che, se modificati dal business, richiedono approvazione admin.
SENSITIVE_BUSINESS_FIELDS = ("phone", "public_email")

EVENT_TYPES = [
    "view", "open_map", "click_phone", "click_maps", "click_website",
    "click_instagram", "click_whatsapp", "open_gallery",
]

# throttle in-memory per il tracking (best-effort, anti doppio-click)
_track_seen: dict[tuple, float] = {}
_track_lock = threading.Lock()
_TRACK_WINDOW = 25  # secondi


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _c():
    return get_client()


# ============================================================
# Completezza profilo + trust score (anche lato server, opzionale)
# ============================================================
def compute_completeness(p: dict) -> int:
    wi = p.get("water_info") or {}
    ex = p.get("extra") or {}
    checks = [
        p.get("business_name"), p.get("category"), p.get("address"), p.get("city"),
        p.get("phone"), p.get("description"), ex.get("long_desc"),
        bool(ex.get("hours")), bool(ex.get("services")),
        any((wi.get("water_type"), ex.get("water"))),
        p.get("logo_url"), p.get("cover_image_url"),
        (p.get("latitude") is not None and p.get("longitude") is not None),
    ]
    return round(sum(1 for c in checks if c) / len(checks) * 100)


def compute_trust(p: dict) -> int:
    score = 0
    score += min(40, compute_completeness(p) * 0.4)
    if p.get("verification_status") and p["verification_status"] != "not_verified":
        score += 20
    if p.get("logo_url") and p.get("cover_image_url"):
        score += 10
    badges = p.get("badges") or []
    score += min(20, len(badges) * 7)
    if (p.get("latitude") is not None and p.get("longitude") is not None):
        score += 10
    return int(min(100, score))


# ============================================================
# Analytics
# ============================================================
def track_event(profile_id: str, event_type: str, session_id: str, device: str) -> bool:
    if event_type not in EVENT_TYPES or not profile_id:
        return False
    key = (profile_id, event_type, session_id or "")
    now = time.time()
    with _track_lock:
        last = _track_seen.get(key, 0)
        if now - last < _TRACK_WINDOW:
            return False
        _track_seen[key] = now
        if len(_track_seen) > 5000:  # evita crescita illimitata
            _track_seen.clear()
    try:
        cl = _c()
        cl.table("business_events").insert({
            "business_profile_id": profile_id, "event_type": event_type,
            "device": device or None, "session_id": session_id or None,
        }).execute()
        # incrementa l'aggregato giornaliero (upsert + somma lato app)
        today = date.today().isoformat()
        existing = cl.table("business_event_daily").select("id,count") \
            .eq("business_profile_id", profile_id).eq("day", today).eq("event_type", event_type).execute().data
        if existing:
            cl.table("business_event_daily").update({"count": (existing[0]["count"] or 0) + 1}) \
                .eq("id", existing[0]["id"]).execute()
        else:
            cl.table("business_event_daily").insert({
                "business_profile_id": profile_id, "day": today,
                "event_type": event_type, "count": 1,
            }).execute()
        return True
    except Exception:
        return False


def get_analytics(profile_id: str, days: int = 30) -> dict:
    days = max(7, min(days, 90))
    start = (date.today() - timedelta(days=days - 1))
    prev_start = start - timedelta(days=days)
    try:
        rows = _c().table("business_event_daily").select("day,event_type,count") \
            .eq("business_profile_id", profile_id).gte("day", prev_start.isoformat()).execute().data or []
    except Exception:
        rows = []
    # serie giornaliera per il periodo corrente
    by_day: dict[str, dict] = {}
    totals: dict[str, int] = {e: 0 for e in EVENT_TYPES}
    prev_totals: dict[str, int] = {e: 0 for e in EVENT_TYPES}
    for d in range(days):
        day = (start + timedelta(days=d)).isoformat()
        by_day[day] = {"day": day, **{e: 0 for e in EVENT_TYPES}}
    for r in rows:
        day = str(r["day"])[:10]
        et = r["event_type"]
        cnt = r["count"] or 0
        if et not in totals:
            continue
        if day in by_day:
            by_day[day][et] = cnt
            totals[et] += cnt
        elif prev_start.isoformat() <= day < start.isoformat():
            prev_totals[et] += cnt
    return {
        "days": days,
        "series": list(by_day.values()),
        "totals": totals,
        "prev_totals": prev_totals,
        "views": totals.get("view", 0),
        "clicks": sum(totals[e] for e in EVENT_TYPES if e.startswith("click_")),
    }


# ============================================================
# Notifiche
# ============================================================
def notify(audience: str, profile_id, type_: str, title: str, body: str = "") -> None:
    try:
        _c().table("business_notifications").insert({
            "audience": audience, "business_profile_id": profile_id,
            "type": type_, "title": title, "body": body,
        }).execute()
    except Exception:
        pass


def list_notifications(audience: str, profile_id=None, limit: int = 50) -> list:
    try:
        q = _c().table("business_notifications").select("*").eq("audience", audience)
        if profile_id:
            q = q.eq("business_profile_id", profile_id)
        return q.order("created_at", desc=True).limit(limit).execute().data or []
    except Exception:
        return []


def mark_notification_read(notif_id: str) -> None:
    try:
        _c().table("business_notifications").update({"read": True}).eq("id", notif_id).execute()
    except Exception:
        pass


# ============================================================
# Audit log
# ============================================================
def audit(profile_id, actor: str, action: str, note: str = "") -> None:
    try:
        _c().table("business_audit_log").insert({
            "business_profile_id": profile_id, "actor": actor, "action": action, "note": note,
        }).execute()
    except Exception:
        pass


def list_audit(limit: int = 100) -> list:
    try:
        return _c().table("business_audit_log").select("*").order("created_at", desc=True).limit(limit).execute().data or []
    except Exception:
        return []


# ============================================================
# Modifiche in attesa
# ============================================================
def create_pending_change(profile_id: str, field: str, old, new, requested_by: str) -> None:
    _c().table("business_pending_changes").insert({
        "business_profile_id": profile_id, "field": field,
        "old_value": str(old) if old is not None else None,
        "new_value": str(new) if new is not None else None,
        "requested_by": requested_by,
    }).execute()
    notify("admin", profile_id, "pending_change", f"Modifica in attesa: {field}", f"Nuovo valore: {new}")
    audit(profile_id, requested_by, "pending_change_requested", field)


def list_pending(status: str = "pending") -> list:
    try:
        q = _c().table("business_pending_changes").select("*, business_profiles(business_name,slug)")
        if status:
            q = q.eq("status", status)
        return q.order("created_at", desc=True).execute().data or []
    except Exception:
        return []


def list_pending_for_profile(profile_id: str) -> list:
    try:
        return _c().table("business_pending_changes").select("*").eq("business_profile_id", profile_id) \
            .order("created_at", desc=True).execute().data or []
    except Exception:
        return []


def resolve_pending(change_id: str, approve: bool, actor: str, notes: str = "") -> dict:
    cl = _c()
    rows = cl.table("business_pending_changes").select("*").eq("id", change_id).execute().data
    if not rows:
        return {"ok": False, "error": "not_found"}
    ch = rows[0]
    if approve:
        import business
        business.update_profile(ch["business_profile_id"], {ch["field"]: ch["new_value"]}, admin=True)
    cl.table("business_pending_changes").update({
        "status": "approved" if approve else "rejected",
        "admin_notes": notes, "updated_at": _now_iso(),
    }).eq("id", change_id).execute()
    notify("business", ch["business_profile_id"],
           "change_resolved", f"Modifica {'approvata' if approve else 'rifiutata'}: {ch['field']}", notes)
    audit(ch["business_profile_id"], actor, f"pending_change_{'approved' if approve else 'rejected'}", ch["field"])
    return {"ok": True}


# ============================================================
# Messaggi admin <-> business
# ============================================================
def list_messages(profile_id: str) -> list:
    try:
        return _c().table("business_messages").select("*").eq("business_profile_id", profile_id) \
            .order("created_at").execute().data or []
    except Exception:
        return []


def send_message(profile_id: str, sender: str, body: str) -> dict | None:
    body = (body or "").strip()[:2000]
    if not body:
        return None
    try:
        res = _c().table("business_messages").insert({
            "business_profile_id": profile_id, "sender": sender, "body": body,
        }).execute()
        notify("business" if sender == "admin" else "admin", profile_id,
               "message", "Nuovo messaggio", body[:120])
        return (res.data or [None])[0]
    except Exception:
        return None


# ============================================================
# Anti-duplicati
# ============================================================
def find_duplicates(app_obj: dict) -> list:
    cl = _c()
    found = {}
    name = (app_obj.get("business_name") or "").strip()
    email = (app_obj.get("contact_email") or "").strip().lower()
    phone = (app_obj.get("contact_phone") or "").strip()
    address = (app_obj.get("address") or "").strip()
    try:
        if name:
            for p in cl.table("business_profiles").select("id,business_name,slug,city").ilike("business_name", name).execute().data or []:
                found[p["id"]] = {"id": p["id"], "type": "profile", "business_name": p["business_name"], "reason": "stesso nome"}
        if email:
            for a in cl.table("business_applications").select("id,business_name,contact_email").eq("contact_email", email).execute().data or []:
                if a["id"] != app_obj.get("id"):
                    found[a["id"]] = {"id": a["id"], "type": "application", "business_name": a["business_name"], "reason": "stessa email"}
        if phone:
            for a in cl.table("business_applications").select("id,business_name,contact_phone").eq("contact_phone", phone).execute().data or []:
                if a["id"] != app_obj.get("id"):
                    found.setdefault(a["id"], {"id": a["id"], "type": "application", "business_name": a["business_name"], "reason": "stesso telefono"})
        if address:
            for p in cl.table("business_profiles").select("id,business_name,address").ilike("address", address).execute().data or []:
                found.setdefault(p["id"], {"id": p["id"], "type": "profile", "business_name": p["business_name"], "reason": "stesso indirizzo"})
    except Exception:
        pass
    return list(found.values())


# ============================================================
# Hook usato da business.py: separa modifiche dirette da quelle in attesa
# ============================================================
def split_business_edit(profile: dict, patch: dict, editable: tuple) -> tuple[dict, dict]:
    """Ritorna (direct, sensitive): campi applicabili subito vs in attesa."""
    direct, sensitive = {}, {}
    for k, v in (patch or {}).items():
        if k not in editable:
            continue
        if k in SENSITIVE_BUSINESS_FIELDS and str(v) != str(profile.get(k) or ""):
            sensitive[k] = v
        else:
            direct[k] = v
    return direct, sensitive


# ============================================================
# Rotte
# ============================================================
def _owner_profile():
    user = supa_auth.require_user()
    import business
    p = business.get_profile_for_user(user)
    if not p:
        abort(404, description="Nessuna attività associata a questo account.")
    return user, p


def register_v2_routes(app) -> None:
    # ---------- Tracking pubblico ----------
    @app.post("/api/business/track")
    def api_track():
        if not SUPABASE_ENABLED:
            return jsonify({"ok": False}), 503
        b = request.get_json(force=True, silent=True) or {}
        import business
        pid = b.get("profile_id")
        if not pid and b.get("slug"):
            prof = business.get_public_profile_by_slug(b["slug"])
            pid = prof.get("id") if prof else None
        ok = track_event(pid, (b.get("event") or "").strip(), b.get("session_id") or "", b.get("device") or "")
        return jsonify({"ok": ok})

    # ---------- Business (titolare) ----------
    @app.get("/api/business/me/analytics")
    def api_me_analytics():
        _user, p = _owner_profile()
        days = int(request.args.get("days", 30) or 30)
        return jsonify(get_analytics(p["id"], days))

    @app.get("/api/business/me/notifications")
    def api_me_notifications():
        _user, p = _owner_profile()
        return jsonify({"items": list_notifications("business", p["id"])})

    @app.post("/api/business/me/notifications/<nid>/read")
    def api_me_notif_read(nid):
        _owner_profile()
        mark_notification_read(nid)
        return jsonify({"ok": True})

    @app.get("/api/business/me/changes")
    def api_me_changes():
        _user, p = _owner_profile()
        return jsonify({"items": list_pending_for_profile(p["id"])})

    @app.get("/api/business/me/messages")
    def api_me_messages():
        _user, p = _owner_profile()
        return jsonify({"items": list_messages(p["id"])})

    @app.post("/api/business/me/messages")
    def api_me_message_send():
        _user, p = _owner_profile()
        body = (request.get_json(force=True, silent=True) or {}).get("body", "")
        m = send_message(p["id"], "business", body)
        return jsonify(m or {}), (201 if m else 400)

    # ---------- Admin ----------
    @app.get("/api/admin/business/analytics/<profile_id>")
    def api_admin_analytics(profile_id):
        supa_auth.require_admin()
        return jsonify(get_analytics(profile_id, int(request.args.get("days", 30) or 30)))

    @app.get("/api/admin/business/notifications")
    def api_admin_notifications():
        supa_auth.require_admin()
        return jsonify({"items": list_notifications("admin")})

    @app.post("/api/admin/business/notifications/<nid>/read")
    def api_admin_notif_read(nid):
        supa_auth.require_admin()
        mark_notification_read(nid)
        return jsonify({"ok": True})

    @app.get("/api/admin/business/pending")
    def api_admin_pending():
        supa_auth.require_admin()
        return jsonify({"items": list_pending(request.args.get("status", "pending"))})

    @app.post("/api/admin/business/pending/<change_id>/approve")
    def api_admin_pending_approve(change_id):
        u = supa_auth.require_admin()
        res = resolve_pending(change_id, True, u.get("email", "admin"), (request.get_json(force=True, silent=True) or {}).get("admin_notes", ""))
        return (jsonify(res), 200) if res.get("ok") else (jsonify(res), 404)

    @app.post("/api/admin/business/pending/<change_id>/reject")
    def api_admin_pending_reject(change_id):
        u = supa_auth.require_admin()
        res = resolve_pending(change_id, False, u.get("email", "admin"), (request.get_json(force=True, silent=True) or {}).get("admin_notes", ""))
        return (jsonify(res), 200) if res.get("ok") else (jsonify(res), 404)

    @app.get("/api/admin/business/audit")
    def api_admin_audit():
        supa_auth.require_admin()
        return jsonify({"items": list_audit()})

    @app.get("/api/admin/business/profiles/<profile_id>/messages")
    def api_admin_messages(profile_id):
        supa_auth.require_admin()
        return jsonify({"items": list_messages(profile_id)})

    @app.post("/api/admin/business/profiles/<profile_id>/messages")
    def api_admin_message_send(profile_id):
        supa_auth.require_admin()
        body = (request.get_json(force=True, silent=True) or {}).get("body", "")
        m = send_message(profile_id, "admin", body)
        return jsonify(m or {}), (201 if m else 400)

    @app.get("/api/admin/business/applications/<app_id>/duplicates")
    def api_admin_duplicates(app_id):
        supa_auth.require_admin()
        import business
        a = business.get_application(app_id)
        if not a:
            abort(404)
        return jsonify({"items": find_duplicates(a)})
