"""
Email transazionali AcquaMap Business via SMTP (Aruba), con smtplib.

Config SOLO da variabili d'ambiente (mai hardcodare/committare la password):
  SMTP_HOST   (es. smtps.aruba.it)
  SMTP_PORT   (es. 465)
  SMTP_SECURE (true -> SSL)
  SMTP_USER   (acquamap@hydroroma.com)
  SMTP_PASS   (in env, MAI nel codice)
  SMTP_FROM_NAME / SMTP_FROM_EMAIL
  APP_PUBLIC_BASE (es. https://hydromap.netlify.app) — base per i link nelle email

Se SMTP_PASS non è configurata, l'invio è un no-op silenzioso (in dev non rompe).
Gli invii avvengono in un thread separato per non bloccare la richiesta Flask.
"""
from __future__ import annotations

import os
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

SMTP_HOST = os.environ.get("SMTP_HOST", "smtps.aruba.it")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_SECURE = os.environ.get("SMTP_SECURE", "true").lower() in ("1", "true", "yes")
SMTP_USER = os.environ.get("SMTP_USER", "acquamap@hydroroma.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_NAME = os.environ.get("SMTP_FROM_NAME", "AcquaMap Business")
FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", SMTP_USER)
APP_BASE = os.environ.get("APP_PUBLIC_BASE", "https://hydromap.netlify.app").rstrip("/")

ENABLED = bool(SMTP_PASS and SMTP_USER)


def _send_sync(to_email: str, subject: str, body: str) -> None:
    if not ENABLED or not to_email:
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Reply-To"] = FROM_EMAIL
    msg["Date"] = formatdate(localtime=True)
    # Message-ID con dominio del mittente: aiuta la reputazione/anti-spam.
    _domain = FROM_EMAIL.split("@")[-1] if "@" in FROM_EMAIL else "hydroroma.com"
    msg["Message-ID"] = make_msgid(domain=_domain)
    msg.set_content(body)
    try:
        if SMTP_SECURE:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=20) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
    except Exception as e:  # noqa: BLE001 — non vogliamo rompere la richiesta
        print(f"[mailer] invio fallito a {to_email}: {e}")


def send(to_email: str, subject: str, body: str) -> None:
    """Invio non bloccante (best-effort)."""
    threading.Thread(target=_send_sync, args=(to_email, subject, body), daemon=True).start()


def _name(obj: dict) -> str:
    return obj.get("contact_name") or "referente"


def _to(obj: dict) -> str:
    return obj.get("contact_email") or obj.get("owner_email") or obj.get("public_email") or ""


def _biz(obj: dict) -> str:
    return obj.get("business_name") or "la tua attività"


# ---------- template ----------
def send_apply_received(app_obj: dict) -> None:
    send(_to(app_obj), "Abbiamo ricevuto la tua richiesta per AcquaMap Business",
         f"""Ciao {_name(app_obj)},

abbiamo ricevuto la richiesta di collaborazione per {_biz(app_obj)}.

Il team AcquaMap esaminerà le informazioni inviate e ti contatterà in caso di
approvazione o necessità di ulteriori dettagli.

Il programma AcquaMap Business Expand è attualmente gratuito per le prime
attività selezionate.

Grazie,
Team AcquaMap""")


def send_onboarding_link(profile: dict, token: str) -> None:
    link = f"{APP_BASE}/business-app/onboarding/{token}"
    send(_to(profile), "Completa il profilo della tua attività su AcquaMap",
         f"""Ciao {_name(profile)},

la richiesta per {_biz(profile)} è stata accettata.

Completa il profilo della tua attività usando questo link privato:

{link}

Da qui potrai inserire foto, descrizione, servizi, informazioni sull'acqua,
orari e contatti pubblici. Il profilo verrà poi revisionato dal team AcquaMap.

Grazie,
Team AcquaMap""")


def send_profile_received(profile: dict) -> None:
    send(_to(profile), "Profilo ricevuto: revisione in corso",
         f"""Ciao {_name(profile)},

abbiamo ricevuto il profilo completo di {_biz(profile)}.

Il team AcquaMap controllerà le informazioni e le immagini prima della
pubblicazione. Ti aggiorneremo appena la revisione sarà completata.

Grazie,
Team AcquaMap""")


def send_published(profile: dict) -> None:
    send(_to(profile), "Il profilo della tua attività è ora online su AcquaMap",
         f"""Ciao {_name(profile)},

il profilo di {_biz(profile)} è stato pubblicato su AcquaMap.

Prossimo passaggio: crea il tuo accesso Business per consultare statistiche e
strumenti dedicati. Riceverai a breve il link per la creazione dell'account.

Grazie,
Team AcquaMap""")


def send_account_link(profile: dict, token: str) -> None:
    link = f"{APP_BASE}/business-app/account/{token}"
    send(_to(profile), "Crea il tuo accesso AcquaMap Business",
         f"""Ciao {_name(profile)},

puoi creare l'accesso alla dashboard business di {_biz(profile)} qui:

{link}

Ti verrà chiesto di impostare una password (per accedere) e un PIN di sicurezza
(per confermare le azioni sensibili).

Grazie,
Team AcquaMap""")
