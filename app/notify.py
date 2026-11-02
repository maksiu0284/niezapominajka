"""Niezapominajka – automatyczne powiadomienia: e-mail (SMTP), SMS (SMSAPI.pl, SMS Gateway for Android).

Raz dziennie, o godzinie ustawionej przez właściciela, program:
1. wysyła osobom odpowiedzialnym za terminy wiadomość, gdy termin wchodzi w okres
   przypomnienia, staje się pilny lub mija (każdy etap tylko raz, po terminie – co N dni),
2. wysyła użytkownikom, którzy tego chcą, zestawienie terminów do zrobienia.
Każda próba wysyłki trafia do dziennika powiadomień.
"""
import base64
import json
import smtplib
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from . import config, db, security, services as svc

_lock = threading.Lock()


class SendError(Exception):
    pass


# ---------------------------------------------------------------- kanały

def email_configured(s):
    return bool(s.get("smtp_host") and (s.get("smtp_from") or s.get("smtp_user")))


def sms_configured(s):
    p = s.get("sms_provider")
    if p == "smsapi":
        return bool(s.get("smsapi_token"))
    if p == "android":
        return bool(s.get("android_user") and s.get("android_password")
                    and (s.get("android_mode") == "cloud" or s.get("android_url")))
    return False


def send_email(s, to, subject, body):
    if not email_configured(s):
        raise SendError("Poczta nie jest skonfigurowana.")
    sender = s.get("smtp_from") or s.get("smtp_user")
    msg = EmailMessage()
    msg["From"] = formataddr((s.get("smtp_from_name") or config.APP_NAME, sender))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    msg.set_content(body)
    host = s["smtp_host"].strip()
    port = int(s.get("smtp_port") or 587)
    mode = s.get("smtp_security") or "starttls"
    try:
        if mode == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=25, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=25)
            if mode == "starttls":
                server.starttls(context=ssl.create_default_context())
        with server:
            if s.get("smtp_user"):
                server.login(s["smtp_user"], s.get("smtp_password") or "")
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise SendError("Serwer poczty odrzucił login lub hasło. Dla Gmaila użyj hasła aplikacji.")
    except (smtplib.SMTPException, OSError) as exc:
        raise SendError(f"Błąd poczty: {exc}")


def _http(url, data=None, headers=None, method=None, timeout=25):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise SendError(f"Brak połączenia: {getattr(exc, 'reason', exc)}")


def _smsapi(s, phone, text):
    params = {"to": phone.lstrip("+"), "message": text, "format": "json", "encoding": "utf-8"}
    if s.get("smsapi_from"):
        params["from"] = s["smsapi_from"]
    if s.get("smsapi_test") == "1":
        params["test"] = "1"
    status, body = _http("https://api.smsapi.pl/sms.do", urllib.parse.urlencode(params).encode(),
                         {"Authorization": "Bearer " + s["smsapi_token"].strip(),
                          "Content-Type": "application/x-www-form-urlencoded"}, "POST")
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    if status >= 400 or "error" in data:
        raise SendError(f"SMSAPI: {data.get('message') or body[:200] or status}")
    return data


def _android(s, phone, text):
    if s.get("android_mode") == "cloud":
        url = "https://api.sms-gate.app/3rdparty/v1/messages"
    else:
        base = (s.get("android_url") or "").strip().rstrip("/")
        if not base.startswith("http"):
            base = "http://" + base
        url = base + "/message"
    auth = base64.b64encode(f"{s['android_user']}:{s['android_password']}".encode()).decode()
    payload = json.dumps({"textMessage": {"text": text}, "phoneNumbers": [phone]}).encode()
    status, body = _http(url, payload, {"Authorization": "Basic " + auth, "Content-Type": "application/json"}, "POST")
    if status == 401:
        raise SendError("Telefon z bramką odrzucił login lub hasło.")
    if status >= 400:
        raise SendError(f"Bramka Android: HTTP {status} {body[:200]}")
    return body


def send_sms(s, phone, text):
    phone = svc.normalize_phone(phone)
    if not phone:
        raise SendError("Brak numeru telefonu.")
    p = s.get("sms_provider")
    if not sms_configured(s):
        raise SendError("Bramka SMS nie jest skonfigurowana.")
    if p == "smsapi":
        return _smsapi(s, phone, text)
    return _android(s, phone, text)


def check_smsapi(s):
    status, body = _http("https://api.smsapi.pl/profile", None,
                         {"Authorization": "Bearer " + (s.get("smsapi_token") or "").strip()})
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    if status >= 400:
        raise SendError(f"SMSAPI: {data.get('message') or status}")
    return data


# ---------------------------------------------------------------- dziennik

def log(kind, channel, recipient, address, term_id, subject, ok, error=""):
    db.execute(
        """INSERT INTO notification_log(ts,kind,channel,recipient,address,term_id,subject,ok,error)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (db.now_str(), kind, channel, recipient, address, term_id, subject, int(ok), error or None),
    )


def recent_log(limit=200):
    return db.query("SELECT * FROM notification_log ORDER BY id DESC LIMIT ?", (limit,))


# ---------------------------------------------------------------- treść

def base_url(s):
    if s.get("public_url"):
        return s["public_url"].rstrip("/")
    return f"http://{svc.lan_address()}:{config.PORT}"


def _system_sender(s):
    return {"full_name": s.get("smtp_from_name") or s.get("company_name") or config.APP_NAME}


def term_messages(term, s, name):
    sender = _system_sender(s)
    sms = svc.render_template(s.get("template_sms"), term, s, sender, name)
    subject = svc.render_template(s.get("template_email_subject"), term, s, sender, name)
    body = svc.render_template(s.get("template_email_body"), term, s, sender, name)
    body += f"\n\nSzczegóły w programie: {base_url(s)}/terminy/{term['id']}\n\n--\nWiadomość wysłana automatycznie przez {config.APP_NAME}."
    return sms, subject, body


def digest_messages(user, terms, s):
    company = s.get("company_name") or config.APP_NAME
    counts = {k: sum(1 for t in terms if t["status_key"] == k) for k in ("overdue", "urgent", "soon")}
    head = f"po terminie: {counts['overdue']}, pilne: {counts['urgent']}, wkrótce: {counts['soon']}"
    subject = f"{config.APP_NAME}: terminy na {date.today().strftime('%d.%m.%Y')} ({head})"
    lines = [f"Dzień dobry {user.get('full_name') or user['username']},", "",
             f"zestawienie terminów do zrobienia w firmie {company} ({head}):", ""]
    for t in terms:
        lines.append(f"• {svc.fmt_date(t['due_date'])} ({t['left_label']}) – {t['display_title']} – {t['object_name']}"
                     + (f" – odpowiada: {t['responsible_name']}" if t["responsible_name"] else ""))
    if not terms:
        lines.append("Brak terminów wymagających uwagi.")
    lines += ["", f"Otwórz program: {base_url(s)}/", "", "--",
              f"Zestawienie wysyła automatycznie {config.APP_NAME}. Wyłączysz je w swoim profilu."]
    sms = f"{config.APP_NAME} {company}: {head}. {base_url(s)}/"
    return sms, subject, "\n".join(lines)


# ---------------------------------------------------------------- przebieg dzienny

def _wants(channel_pref, channel):
    return channel_pref == "both" or channel_pref == channel


def _already(term_id, recipient, channel, stage, repeat_days):
    if stage != "overdue":
        return bool(db.one("SELECT 1 FROM notification_sent WHERE term_id=? AND recipient=? AND channel=? AND stage=?",
                           (term_id, recipient, channel, stage)))
    row = db.one("SELECT MAX(ts) AS ts FROM notification_sent WHERE term_id=? AND recipient=? AND channel=? AND stage LIKE 'overdue%'",
                 (term_id, recipient, channel))
    if not row or not row["ts"]:
        return False
    if repeat_days <= 0:
        return True
    last = datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")
    return datetime.now() - last < timedelta(days=repeat_days) - timedelta(hours=1)


def _mark(term_id, recipient, channel, stage):
    if stage == "overdue":
        stage = "overdue-" + date.today().isoformat()
    db.execute("INSERT OR REPLACE INTO notification_sent(term_id,recipient,channel,stage,ts) VALUES(?,?,?,?,?)",
               (term_id, recipient, channel, stage, db.now_str()))


def run_daily(trigger="auto", user=None):
    """Wysyła powiadomienia. Zwraca słownik z liczbą wysłanych i błędów."""
    if not _lock.acquire(blocking=False):
        return {"sent": 0, "errors": 0, "skipped": "Wysyłka już trwa."}
    try:
        return _run(trigger, user)
    finally:
        _lock.release()


def _run(trigger, user):
    s = db.get_settings()
    stats = {"sent": 0, "errors": 0}
    has_mail, has_sms = email_configured(s), sms_configured(s)
    repeat = int(s.get("notify_repeat_days") or 0)
    stages_on = {k for k in ("soon", "urgent", "overdue") if s.get(f"notify_stage_{k}", "1") == "1"}
    open_terms = svc.enrich_terms(db.query("SELECT * FROM terms WHERE status='open' ORDER BY due_date"), s)

    def deliver(kind, channel, rec_key, rec_name, address, term, subject, text, body=None):
        try:
            if channel == "email":
                send_email(s, address, subject, body)
            else:
                send_sms(s, address, text)
            log(kind, channel, rec_name, address, term["id"] if term else None, subject, True)
            stats["sent"] += 1
            return True
        except SendError as exc:
            log(kind, channel, rec_name, address, term["id"] if term else None, subject, False, str(exc))
            stats["errors"] += 1
            return False

    # 1) osoby odpowiedzialne
    for t in open_terms:
        stage = t["status_key"]
        if stage not in stages_on:
            continue
        emp = t.get("responsible")
        if not emp or emp.get("notify_channel", "none") == "none":
            continue
        name = f"{emp['first_name']} {emp['last_name']}"
        rec_key = f"emp:{emp['id']}"
        sms_text, subject, body = term_messages(t, s, emp["first_name"])
        if has_mail and _wants(emp["notify_channel"], "email") and emp.get("email"):
            if not _already(t["id"], rec_key, "email", stage, repeat):
                if deliver("termin", "email", rec_key, name, emp["email"], t, subject, sms_text, body):
                    _mark(t["id"], rec_key, "email", stage)
        if has_sms and _wants(emp["notify_channel"], "sms") and emp.get("phone"):
            if not _already(t["id"], rec_key, "sms", stage, repeat):
                if deliver("termin", "sms", rec_key, name, emp["phone"], t, subject, sms_text):
                    _mark(t["id"], rec_key, "sms", stage)

    # 2) zestawienia dla użytkowników programu
    for u in db.query("SELECT * FROM users WHERE active=1 AND notify_channel!='none'"):
        perms = security.load_permissions(u)
        where, params = svc.visible_terms_sql(u, perms)
        terms = svc.enrich_terms(db.query(f"SELECT * FROM terms WHERE status='open' AND {where} ORDER BY due_date", params), s)
        terms = [t for t in terms if t["status_key"] in ("overdue", "urgent", "soon")]
        if not terms and s.get("notify_digest_empty") != "1":
            continue
        sms_text, subject, body = digest_messages(u, terms, s)
        name = u.get("full_name") or u["username"]
        if has_mail and _wants(u["notify_channel"], "email") and u.get("email"):
            deliver("zestawienie", "email", f"user:{u['id']}", name, u["email"], None, subject, sms_text, body)
        if has_sms and _wants(u["notify_channel"], "sms") and u.get("phone") and terms:
            deliver("zestawienie", "sms", f"user:{u['id']}", name, u["phone"], None, subject, sms_text)

    desc = f"Automatyczne powiadomienia ({'ręcznie' if trigger == 'manual' else 'o ustalonej godzinie'}): wysłano {stats['sent']}, błędów {stats['errors']}"
    security.audit(user, "notify_auto", None, "powiadomienia", None, desc)
    return stats


def worker_tick():
    """Wywoływane co minutę przez wątek w tle."""
    s = db.get_settings()
    if s.get("setup_done") != "1" or s.get("notify_enabled") != "1":
        return
    now = datetime.now()
    today = now.date().isoformat()
    if s.get("notify_last_run") == today:
        return
    if now.hour < int(s.get("notify_hour") or 7):
        return
    db.set_setting("notify_last_run", today)
    run_daily("auto")
