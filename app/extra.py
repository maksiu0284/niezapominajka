"""Niezapominajka – strony dodatkowe: pomoc, o programie, powiadomienia automatyczne, dostęp zdalny,
logowanie dwuetapowe, kalendarz i import z Excela."""
import json
import secrets
import shutil
import subprocess
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from starlette.datastructures import UploadFile

from . import config, db, importer, notify, security, services as svc, totp
from .main import _filtered_terms, app, ctx, templates, flash, form_data, go, int_or_none, load_user, owner_exists, render


templates.env.globals["public_base"] = lambda: notify.base_url(db.get_settings())


def _optional_ctx(request):
    """Kontekst dla stron dostępnych także bez logowania (pomoc, o programie)."""
    if owner_exists() and load_user(request):
        try:
            return ctx(request)
        except Exception:
            return None
    return None


# ======================================================================
#  POMOC I O PROGRAMIE
# ======================================================================

@app.get("/pomoc", response_class=HTMLResponse)
def help_page(request: Request):
    c = _optional_ctx(request)
    return render(request, "help.html", c, lan=f"http://{svc.lan_address()}:{config.PORT}")


@app.get("/o-programie", response_class=HTMLResponse)
def about_page(request: Request):
    c = _optional_ctx(request)
    return render(request, "about.html", c, third_party=config.THIRD_PARTY, license_name=config.LICENSE_NAME,
                  lan=f"http://{svc.lan_address()}:{config.PORT}", data_dir=str(config.DATA_DIR) if c and c.is_owner else None)


def _license_text():
    for p in (config.ROOT_DIR / "LICENSE", config.BASE_DIR / "LICENSE", config.BASE_DIR.parent / "LICENSE"):
        if p.exists():
            return p.read_text(encoding="utf-8")
    return f"{config.LICENSE_NAME}\nhttps://www.gnu.org/licenses/agpl-3.0.html\n"


@app.get("/licencja")
def license_page():
    return PlainTextResponse(_license_text())


# ======================================================================
#  LOGOWANIE DWUETAPOWE (profil)
# ======================================================================

@app.get("/profil/2fa", response_class=HTMLResponse)
def twofa_page(request: Request, wymagane: int = 0):
    c = ctx(request)
    enabled_globally = c.settings.get("twofa_enabled") == "1"
    setup = None
    if enabled_globally and not c.user["totp_enabled"]:
        secret = request.session.get("totp_setup") or totp.new_secret()
        request.session["totp_setup"] = secret
        uri = totp.provisioning_uri(secret, c.user["username"], f"{config.APP_NAME} {c.settings.get('company_name') or ''}".strip())
        setup = {"secret": totp.pretty(secret), "qr": totp.qr_svg(uri), "uri": uri}
    return render(request, "twofa.html", c, setup=setup, required=bool(wymagane) or c.is_owner,
                  enabled_globally=enabled_globally, errors=[])


@app.post("/profil/2fa/wlacz")
async def twofa_enable(request: Request):
    c = ctx(request)
    form = await form_data(request)
    secret = request.session.get("totp_setup")
    if c.settings.get("twofa_enabled") != "1" or not secret:
        return go("/profil/2fa")
    counter = totp.verify(secret, form.get("code"))
    if counter is None:
        uri = totp.provisioning_uri(secret, c.user["username"], config.APP_NAME)
        return render(request, "twofa.html", c, setup={"secret": totp.pretty(secret), "qr": totp.qr_svg(uri), "uri": uri},
                      required=c.is_owner, enabled_globally=True,
                      errors=["Kod się nie zgadza. Wpisz aktualny 6-cyfrowy kod z aplikacji."])
    db.execute("UPDATE users SET totp_secret=?, totp_enabled=1, totp_last=? WHERE id=?", (secret, counter, c.user["id"]))
    request.session.pop("totp_setup", None)
    c.audit("twofa", None, "konto", c.user["id"], "Włączono logowanie dwuetapowe na własnym koncie")
    flash(request, "Logowanie dwuetapowe jest włączone. Przy następnym logowaniu program poprosi o kod z telefonu.")
    return go("/profil")


@app.post("/profil/2fa/wylacz")
async def twofa_disable(request: Request):
    c = ctx(request)
    form = await form_data(request)
    if c.is_owner and c.settings.get("twofa_enabled") == "1":
        flash(request, "Dla właścicieli logowanie dwuetapowe jest obowiązkowe. Możesz je tylko skonfigurować ponownie.", "warn")
        return go("/profil/2fa")
    if not security.verify_password(form.get("current") or "", c.user["password_hash"]):
        flash(request, "Podaj poprawne obecne hasło.", "error")
        return go("/profil/2fa")
    db.execute("UPDATE users SET totp_secret=NULL, totp_enabled=0, totp_last=NULL WHERE id=?", (c.user["id"],))
    c.audit("twofa", None, "konto", c.user["id"], "Wyłączono logowanie dwuetapowe na własnym koncie")
    flash(request, "Logowanie dwuetapowe wyłączone.")
    return go("/profil")


@app.post("/profil/2fa/od-nowa")
async def twofa_reconfigure(request: Request):
    c = ctx(request)
    form = await form_data(request)
    if not security.verify_password(form.get("current") or "", c.user["password_hash"]):
        flash(request, "Podaj poprawne obecne hasło.", "error")
        return go("/profil/2fa")
    db.execute("UPDATE users SET totp_secret=NULL, totp_enabled=0, totp_last=NULL WHERE id=?", (c.user["id"],))
    request.session.pop("totp_setup", None)
    c.audit("twofa", None, "konto", c.user["id"], "Rozpoczęto ponowną konfigurację logowania dwuetapowego")
    return go("/profil/2fa")


@app.post("/panel/uzytkownicy/{uid}/2fa-reset")
async def twofa_reset_user(request: Request, uid: int):
    c = ctx(request)
    c.require_owner()
    await form_data(request)
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise HTTPException(404)
    db.execute("UPDATE users SET totp_secret=NULL, totp_enabled=0, totp_last=NULL, session_version=session_version+1 WHERE id=?", (uid,))
    c.audit("twofa", None, "konto", uid, f"Wyłączono logowanie dwuetapowe dla {u['username']} (np. zgubiony telefon)")
    flash(request, f"Wyłączono logowanie dwuetapowe dla {u['username']}. Przy następnym logowaniu skonfiguruje je od nowa.")
    return go(f"/panel/uzytkownicy/{uid}")


# ======================================================================
#  KALENDARZ (.ics)
# ======================================================================

def _calendar_terms(user):
    perms = security.load_permissions(user)
    where, params = svc.visible_terms_sql(user, perms)
    s = db.get_settings()
    return svc.enrich_terms(db.query(f"SELECT * FROM terms WHERE status='open' AND {where} ORDER BY due_date", params), s), s


@app.get("/kalendarz/{token}.ics")
def calendar_feed(token: str):
    if len(token) < 20:
        raise HTTPException(404)
    user = db.one("SELECT * FROM users WHERE calendar_token=? AND active=1", (token,))
    if not user:
        raise HTTPException(404)
    terms, s = _calendar_terms(user)
    return Response(svc.terms_to_ics(terms, s, notify.base_url(s)), media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "no-cache"})


@app.get("/eksport/kalendarz.ics")
def calendar_download(request: Request, widok: str = "all", modul: str = "", q: str = "", moje: int = 0):
    c = ctx(request)
    module = modul if modul in config.MODULES else None
    terms = [t for t in _filtered_terms(c, module, widok if widok != "done" else "all", q.strip(), bool(moje))
             if t["status"] == "open"]
    c.audit("export", module, "kalendarz", None, f"Eksport do kalendarza (.ics, {len(terms)} terminów)")
    return Response(svc.terms_to_ics(terms, c.settings, notify.base_url(c.settings)), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="niezapominajka.ics"'})


@app.post("/profil/kalendarz")
async def calendar_token_new(request: Request):
    c = ctx(request)
    await form_data(request)
    db.execute("UPDATE users SET calendar_token=? WHERE id=?", (secrets.token_urlsafe(24), c.user["id"]))
    c.audit("calendar", None, "konto", c.user["id"], "Utworzono nowy adres subskrypcji kalendarza")
    flash(request, "Utworzono nowy adres kalendarza. Poprzedni adres przestał działać.")
    return go("/profil#kalendarz")


@app.post("/profil/kalendarz/usun")
async def calendar_token_delete(request: Request):
    c = ctx(request)
    await form_data(request)
    db.execute("UPDATE users SET calendar_token=NULL WHERE id=?", (c.user["id"],))
    c.audit("calendar", None, "konto", c.user["id"], "Wyłączono subskrypcję kalendarza")
    flash(request, "Subskrypcja kalendarza wyłączona.")
    return go("/profil#kalendarz")


# ======================================================================
#  PANEL: POWIADOMIENIA AUTOMATYCZNE
# ======================================================================

NOTIFY_KEYS = ["notify_enabled", "notify_hour", "notify_stage_soon", "notify_stage_urgent", "notify_stage_overdue",
               "notify_repeat_days", "notify_digest_empty", "smtp_host", "smtp_port", "smtp_security", "smtp_user",
               "smtp_password", "smtp_from", "smtp_from_name", "sms_provider", "smsapi_token", "smsapi_from",
               "smsapi_test", "android_mode", "android_url", "android_user", "android_password"]
CHECKBOXES = {"notify_enabled", "notify_stage_soon", "notify_stage_urgent", "notify_stage_overdue",
              "notify_digest_empty", "smtp_test", "smsapi_test"}


def _notify_ctx(c, errors=None, values=None):
    s = dict(values or c.settings)
    recipients = {
        "employees": db.query("SELECT id, first_name, last_name, email, phone, notify_channel FROM employees WHERE notify_channel!='none' ORDER BY last_name"),
        "users": db.query("SELECT id, username, full_name, email, phone, notify_channel FROM users WHERE active=1 AND notify_channel!='none' ORDER BY username"),
    }
    return dict(s=s, errors=errors or [], log=notify.recent_log(100), recipients=recipients,
                providers=config.SMS_PROVIDERS, email_ok=notify.email_configured(c.settings),
                sms_ok=notify.sms_configured(c.settings), secrets_set={k: bool(c.settings.get(k)) for k in config.SECRET_SETTINGS})


@app.get("/panel/powiadomienia", response_class=HTMLResponse)
def notify_page(request: Request):
    c = ctx(request)
    c.require_owner()
    return render(request, "panel/notify.html", c, **_notify_ctx(c))


@app.post("/panel/powiadomienia")
async def notify_save(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    before = dict(c.settings)
    new = {}
    for k in NOTIFY_KEYS:
        if k in CHECKBOXES:
            new[k] = "1" if form.get(k) else "0"
        elif k in config.SECRET_SETTINGS:
            v = form.get(k) or ""
            if form.get(k + "_clear"):
                new[k] = ""
            elif v.strip():
                new[k] = v.strip()
        else:
            new[k] = (form.get(k) or "").strip()
    errors = []
    hour = int_or_none(new["notify_hour"])
    if hour is None or not 0 <= hour <= 23:
        errors.append("Godzina wysyłki: 0–23.")
    port = int_or_none(new["smtp_port"])
    if new["smtp_host"] and (port is None or not 1 <= port <= 65535):
        errors.append("Port serwera poczty: liczba 1–65535 (zwykle 587 albo 465).")
    if new["smtp_security"] not in ("starttls", "ssl", "none"):
        new["smtp_security"] = "starttls"
    if new["sms_provider"] not in config.SMS_PROVIDERS:
        new["sms_provider"] = "none"
    if new["android_mode"] not in ("local", "cloud"):
        new["android_mode"] = "local"
    rep = int_or_none(new["notify_repeat_days"])
    if rep is None or not 0 <= rep <= 90:
        errors.append("Powtarzanie po terminie: 0–90 dni (0 = tylko raz).")
    if new["smtp_from"] and "@" not in new["smtp_from"]:
        errors.append("Adres nadawcy musi być adresem e-mail.")
    if new["sms_provider"] == "android" and new["android_mode"] == "local" and not new["android_url"]:
        errors.append("Podaj adres telefonu z bramką SMS (np. http://192.168.1.50:8080).")
    if errors:
        vals = dict(c.settings)
        vals.update(new)
        return render(request, "panel/notify.html", c, **_notify_ctx(c, errors, vals))
    for k, v in new.items():
        db.set_setting(k, v)
    after = db.get_settings()
    c.audit("settings", None, "powiadomienia", None, "Zmieniono ustawienia powiadomień automatycznych",
            {k: before.get(k) for k in NOTIFY_KEYS}, {k: after.get(k) for k in NOTIFY_KEYS})
    flash(request, "Zapisano ustawienia powiadomień.")
    return go("/panel/powiadomienia")


@app.post("/panel/powiadomienia/test")
async def notify_test(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    channel = form.get("channel")
    address = (form.get("address") or "").strip()
    s = db.get_settings()
    company = s.get("company_name") or config.APP_NAME
    try:
        if channel == "email":
            if "@" not in address:
                raise notify.SendError("Podaj adres e-mail do testu.")
            notify.send_email(s, address, f"{config.APP_NAME}: wiadomość testowa",
                              f"To jest wiadomość testowa z programu {config.APP_NAME} firmy {company}.\n\n"
                              f"Jeśli ją widzisz, wysyłka e-maili działa.\n\n{notify.base_url(s)}/")
        elif channel == "sms":
            notify.send_sms(s, address, f"{config.APP_NAME} {company}: SMS testowy. Wysyłka działa.")
        elif channel == "smsapi_profile":
            data = notify.check_smsapi(s)
            flash(request, f"Połączenie z SMSAPI działa. Punkty na koncie: {data.get('points', '?')}.")
            return go("/panel/powiadomienia#sms")
        else:
            raise HTTPException(400)
        notify.log("test", "email" if channel == "email" else "sms", address, address, None, "Wiadomość testowa", True)
        c.audit("notify_test", None, "powiadomienia", None, f"Test {channel}: wysłano do {address}")
        flash(request, f"Wysłano wiadomość testową na {address}." + (" (SMSAPI w trybie testowym nie wysyła SMS-a naprawdę.)" if channel == "sms" and s.get("sms_provider") == "smsapi" and s.get("smsapi_test") == "1" else ""))
    except notify.SendError as exc:
        notify.log("test", "email" if channel == "email" else "sms", address, address, None, "Wiadomość testowa", False, str(exc))
        flash(request, f"Test nie powiódł się: {exc}", "error")
    return go("/panel/powiadomienia#" + ("email" if channel == "email" else "sms"))


@app.post("/panel/powiadomienia/uruchom")
async def notify_run_now(request: Request):
    c = ctx(request)
    c.require_owner()
    await form_data(request)
    stats = notify.run_daily("manual", c.user)
    if stats.get("skipped"):
        flash(request, stats["skipped"], "warn")
    else:
        flash(request, f"Wysyłka zakończona: wysłano {stats['sent']}, błędów {stats['errors']}.",
              "ok" if not stats["errors"] else "warn")
    return go("/panel/powiadomienia#dziennik")


# ======================================================================
#  PANEL: DOSTĘP ZDALNY
# ======================================================================

def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)


def _remote_status():
    st = {"tailscale": shutil.which("tailscale"), "cloudflared": shutil.which("cloudflared"),
          "ts_name": None, "ts_online": None, "ts_serve": None}
    if st["tailscale"]:
        code, out = _run([st["tailscale"], "status", "--json"])
        if code == 0:
            try:
                data = json.loads(out)
                me = data.get("Self") or {}
                st["ts_name"] = (me.get("DNSName") or "").rstrip(".") or None
                st["ts_online"] = data.get("BackendState") == "Running"
            except ValueError:
                pass
        code, out = _run([st["tailscale"], "serve", "status"])
        st["ts_serve"] = out.strip()[:800] if code == 0 else None
    return st


@app.get("/panel/dostep-zdalny", response_class=HTMLResponse)
def remote_page(request: Request):
    c = ctx(request)
    c.require_owner()
    return render(request, "panel/remote.html", c, modes=config.REMOTE_MODES, st=_remote_status(), errors=[],
                  port=config.PORT, lan=f"http://{svc.lan_address()}:{config.PORT}", output=None)


@app.post("/panel/dostep-zdalny")
async def remote_save(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    before = {k: c.settings.get(k) for k in ("remote_mode", "public_url", "https_cert", "https_key")}
    mode = form.get("remote_mode") if form.get("remote_mode") in config.REMOTE_MODES else "off"
    url = (form.get("public_url") or "").strip().rstrip("/")
    cert, key = (form.get("https_cert") or "").strip(), (form.get("https_key") or "").strip()
    errors = []
    if url and not url.startswith(("https://", "http://")):
        errors.append("Adres publiczny musi zaczynać się od https://")
    if bool(cert) != bool(key):
        errors.append("Podaj oba pliki: certyfikat i klucz – albo żaden.")
    for p in (cert, key):
        if p and not Path(p).exists():
            errors.append(f"Nie znaleziono pliku: {p}")
    if errors:
        c.settings.update(remote_mode=mode, public_url=url, https_cert=cert, https_key=key)
        return render(request, "panel/remote.html", c, modes=config.REMOTE_MODES, st=_remote_status(), errors=errors,
                      port=config.PORT, lan=f"http://{svc.lan_address()}:{config.PORT}", output=None)
    restart = (cert, key) != (c.settings.get("https_cert") or "", c.settings.get("https_key") or "")
    for k, v in {"remote_mode": mode, "public_url": url, "https_cert": cert, "https_key": key}.items():
        db.set_setting(k, v)
    c.audit("remote", None, "dostęp zdalny", None, f"Dostęp zdalny: {config.REMOTE_MODES[mode]}", before,
            {"remote_mode": mode, "public_url": url, "https_cert": cert, "https_key": key})
    msg = "Zapisano ustawienia dostępu zdalnego."
    if restart:
        msg += " Zmiana certyfikatu HTTPS zadziała po ponownym uruchomieniu programu."
    if mode != "off" and c.settings.get("twofa_enabled") != "1":
        flash(request, "Przy dostępie spoza firmy zalecamy włączenie logowania dwuetapowego (Ustawienia → Bezpieczeństwo).", "warn")
    flash(request, msg)
    return go("/panel/dostep-zdalny")


@app.post("/panel/dostep-zdalny/tailscale")
async def remote_tailscale(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    ts = shutil.which("tailscale")
    if not ts:
        flash(request, "Nie znaleziono programu Tailscale na tym komputerze. Zainstaluj go według instrukcji poniżej.", "error")
        return go("/panel/dostep-zdalny")
    action = form.get("action")
    if action == "on":
        code, out = _run([ts, "serve", "--bg", f"http://127.0.0.1:{config.PORT}"], timeout=30)
    else:
        code, out = _run([ts, "serve", "reset"], timeout=30)
    c.audit("remote", None, "dostęp zdalny", None, f"Tailscale serve {'włączenie' if action == 'on' else 'wyłączenie'}: kod {code}")
    st = _remote_status()
    if code == 0 and action == "on" and st.get("ts_name"):
        db.set_setting("remote_mode", "tailscale")
        db.set_setting("public_url", f"https://{st['ts_name']}")
    c.settings = db.get_settings()
    return render(request, "panel/remote.html", c, modes=config.REMOTE_MODES, st=st, errors=[],
                  port=config.PORT, lan=f"http://{svc.lan_address()}:{config.PORT}",
                  output={"ok": code == 0, "text": out.strip() or ("Gotowe." if code == 0 else "Brak odpowiedzi.")})


# ======================================================================
#  PANEL: BEZPIECZEŃSTWO I AKTUALIZACJE (sekcja w Ustawieniach)
# ======================================================================

@app.post("/panel/ustawienia/bezpieczenstwo")
async def security_save(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    twofa = "1" if form.get("twofa_enabled") else "0"
    upd = "1" if form.get("update_check") else "0"
    if twofa != c.settings.get("twofa_enabled"):
        db.set_setting("twofa_enabled", twofa)
        c.audit("twofa", None, "ustawienia", None, "Włączono logowanie dwuetapowe (obowiązkowe dla właścicieli)" if twofa == "1"
                else "Wyłączono logowanie dwuetapowe w całym programie")
    if upd != c.settings.get("update_check"):
        db.set_setting("update_check", upd)
        c.audit("update_check", None, "ustawienia", None, "Włączono sprawdzanie aktualizacji" if upd == "1" else "Wyłączono sprawdzanie aktualizacji")
    flash(request, "Zapisano ustawienia bezpieczeństwa i aktualizacji.")
    if twofa == "1" and not c.user["totp_enabled"]:
        return go("/profil/2fa?wymagane=1")
    return go("/panel/ustawienia#bezpieczenstwo")


@app.post("/panel/aktualizacje/sprawdz")
async def updates_check_now(request: Request):
    c = ctx(request)
    c.require_owner()
    await form_data(request)
    try:
        latest, url = svc.check_updates()
        c.audit("update_check", None, "aktualizacje", None, f"Sprawdzono aktualizacje: najnowsza {latest or 'brak wydań'}")
        if not latest:
            flash(request, "Na stronie projektu nie ma jeszcze opublikowanych wydań.", "warn")
        elif svc.update_available(db.get_settings()):
            flash(request, f"Dostępna jest nowa wersja {latest}. Pobierzesz ją ze strony projektu.", "warn")
        else:
            flash(request, f"Masz najnowszą wersję ({config.APP_VERSION}).")
    except RuntimeError as exc:
        flash(request, str(exc), "error")
    return go("/panel/ustawienia#bezpieczenstwo")


# ======================================================================
#  PANEL: IMPORT Z EXCELA
# ======================================================================

@app.get("/panel/import", response_class=HTMLResponse)
def import_page(request: Request):
    c = ctx(request)
    c.require_owner()
    return render(request, "panel/import.html", c, preview=None, errors=[], warnings=[], token=None, upload_error=None)


@app.get("/panel/import/wzor.xlsx")
def import_template(request: Request):
    c = ctx(request)
    c.require_owner()
    return Response(importer.template_xlsx(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="niezapominajka-wzor-importu.xlsx"'})


def _clean_tmp():
    import time
    for f in config.TMP_DIR.glob("import-*.xlsx"):
        try:
            if time.time() - f.stat().st_mtime > 3600:
                f.unlink()
        except OSError:
            pass


@app.post("/panel/import", response_class=HTMLResponse)
async def import_upload(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    up = form.get("file")
    if not isinstance(up, UploadFile) or not up.filename:
        return render(request, "panel/import.html", c, preview=None, errors=[], warnings=[], token=None,
                      upload_error="Wybierz plik .xlsx.")
    content = await up.read()
    if len(content) > config.MAX_UPLOAD_MB * 1024 * 1024:
        return render(request, "panel/import.html", c, preview=None, errors=[], warnings=[], token=None,
                      upload_error=f"Plik jest za duży (limit {config.MAX_UPLOAD_MB} MB).")
    plan, errors, warnings = importer.parse(content)
    token = None
    if plan and not errors:
        _clean_tmp()
        token = secrets.token_hex(12)
        (config.TMP_DIR / f"import-{token}.xlsx").write_bytes(content)
        request.session["import_token"] = token
    preview = None
    if plan:
        preview = {k: len(plan[k]) for k in ("employees", "vehicles", "machines", "terms")}
        preview["categories"] = len(plan["new_categories"])
        preview["sample_terms"] = plan["terms"][:15]
        preview["filename"] = up.filename
    return render(request, "panel/import.html", c, preview=preview, errors=errors, warnings=warnings, token=token,
                  upload_error=None)


@app.post("/panel/import/zatwierdz")
async def import_confirm(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    token = form.get("token") or ""
    if not token or token != request.session.get("import_token"):
        flash(request, "Podgląd wygasł. Wgraj plik ponownie.", "warn")
        return go("/panel/import")
    path = config.TMP_DIR / f"import-{token}.xlsx"
    if not path.exists():
        flash(request, "Plik importu wygasł. Wgraj go ponownie.", "warn")
        return go("/panel/import")
    plan, errors, _ = importer.parse(path.read_bytes())
    if errors:
        flash(request, "Dane w programie zmieniły się od podglądu. Sprawdź plik ponownie.", "error")
        return go("/panel/import")
    try:
        svc.create_backup("przed-importem")
    except Exception:
        pass
    counts = importer.apply(plan, c.user["id"])
    path.unlink(missing_ok=True)
    request.session.pop("import_token", None)
    desc = (f"Import z Excela: pracownicy {counts['employees']}, pojazdy {counts['vehicles']}, maszyny {counts['machines']}, "
            f"terminy {counts['terms']}, nowe rodzaje spraw {counts['categories']}")
    c.audit("import", None, "import", None, desc, None, counts)
    flash(request, desc + ". Przed importem program zrobił kopię zapasową.")
    return go("/")
