"""Niezapominajka – przypominajka ważnych terminów w firmie.

Aplikacja webowa (FastAPI + Jinja2 + SQLite) działająca na serwerze w sieci firmowej.
Copyright (C) 2026 Maksymilian Staszewski <maksymilianstaszewski@gmail.com>
Licencja: GNU AGPL-3.0 – https://github.com/maksiu0284/niezapominajka
"""
import json
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from . import config, db, files, notify, security, services as svc, sessions, totp

# ======================================================================
#  START APLIKACJI
# ======================================================================


def _worker():
    """Zadania w tle: kopia zapasowa raz na dobę, powiadomienia automatyczne, sprawdzanie aktualizacji."""
    tick = 0
    while True:
        try:
            s = db.get_settings()
            if tick % 30 == 0:
                sessions.purge_expired()
            if s.get("setup_done") == "1":
                if tick % 60 == 0:
                    age = svc.last_auto_backup_age_hours()
                    if age is None or age >= 24:
                        svc.create_backup("auto")
                notify.worker_tick()
                if s.get("update_check") == "1" and tick % 60 == 5:
                    checked = s.get("update_checked_at") or ""
                    if not checked or (datetime.now() - datetime.strptime(checked, "%Y-%m-%d %H:%M:%S")).total_seconds() > 86400:
                        try:
                            svc.check_updates()
                        except Exception:
                            pass
        except Exception as exc:  # zadania w tle nie mogą zatrzymać programu
            print("Błąd zadania w tle:", exc)
        tick += 1
        time.sleep(60)


@asynccontextmanager
async def lifespan(app):
    db.init()
    security.burn_password_check("")  # przygotowuje hash porównawczy – pierwsze logowanie nie zdradza czasu
    threading.Thread(target=_worker, daemon=True).start()
    yield


db.init()
app = FastAPI(title=config.APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# Polityka treści stron programu: skrypty i style tylko z programu, bez osadzania w obcych ramkach.
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'; manifest-src 'self'; worker-src 'self'")


class SecurityHeadersMiddleware:
    """Nagłówki bezpieczeństwa dla każdej odpowiedzi; strony po zalogowaniu nie trafiają do pamięci podręcznej."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        static = path.startswith("/static/") or path in ("/sw.js", "/manifest.webmanifest", "/offline")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers") or [])
                present = {k.lower() for k, _ in hdrs}
                add = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"same-origin",
                    b"content-security-policy": PAGE_CSP.encode(),
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                }
                if not static:
                    add[b"cache-control"] = b"no-store"
                for k, v in add.items():
                    if k not in present:
                        hdrs.append((k, v))
                message["headers"] = hdrs
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(sessions.ServerSessionMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory=config.BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=config.BASE_DIR / "templates")
templates.env.filters["d"] = svc.fmt_date
templates.env.filters["size"] = svc.human_size
templates.env.globals.update(
    MODULES=config.MODULES, ACTIONS=config.ACTIONS, UNITS=config.INTERVAL_UNITS,
    APP_NAME=config.APP_NAME, APP_VERSION=config.APP_VERSION, STATUS_LABELS=svc.STATUS_LABELS,
    APP_TAGLINE=config.APP_TAGLINE, HOMEPAGE=config.HOMEPAGE, SPONSOR_URL=config.SPONSOR_URL,
    AUTHOR=config.AUTHOR, AUTHOR_EMAIL=config.AUTHOR_EMAIL, USER_CHANNELS=config.USER_CHANNELS,
    update_available=svc.update_available, REMOTE_MODES=config.REMOTE_MODES,
    lan_url=lambda: f"http://{svc.lan_address()}:{config.PORT}",
)


# ======================================================================
#  NARZĘDZIA ŻĄDAŃ
# ======================================================================

class Redirect(Exception):
    def __init__(self, url):
        self.url = url


@app.exception_handler(Redirect)
async def _redirect_handler(request, exc):
    return RedirectResponse(exc.url, status_code=303)


@app.exception_handler(HTTPException)
async def _http_error(request, exc):
    msgs = {403: "Brak uprawnień do tej operacji.", 404: "Nie znaleziono strony lub rekordu.",
            400: "Nieprawidłowe żądanie. Odśwież stronę i spróbuj ponownie."}
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": exc.detail or msgs.get(exc.status_code, "Błąd")}, status_code=exc.status_code)
    return templates.TemplateResponse(
        request, "error.html",
        {"code": exc.status_code, "message": exc.detail if isinstance(exc.detail, str) and exc.detail not in ("Not Found", "Forbidden", "Bad Request") else msgs.get(exc.status_code, "Wystąpił błąd."),
         "user": None, "perms": None, "settings": db.get_settings(), "flashes": [], "csrf": ""},
        status_code=exc.status_code,
    )


def client_ip(request):
    return request.client.host if request.client else None


def safe_back(value, default="/"):
    """Adres powrotu tylko w obrębie programu (ścieżka od „/”, bez „//” i bez znaków sterujących)."""
    v = str(value or "").strip()
    if (not v.startswith("/") or v.startswith("//") or v.startswith("/\\")
            or any(ch in v for ch in ("\\", "\r", "\n", "\t")) or len(v) > 500):
        return default
    return v


def insecure_connection(request):
    """Połączenie bez szyfrowania z innego urządzenia niż ten komputer."""
    host = client_ip(request) or ""
    return not sessions.is_https(request.scope) and host not in ("127.0.0.1", "::1", "localhost")


def flash(request, message, kind="ok"):
    request.session.setdefault("flash", [])
    request.session["flash"] = request.session["flash"] + [[kind, message]]


def owner_exists():
    return bool(db.one("SELECT id FROM users WHERE role='owner' LIMIT 1"))


class Ctx:
    def __init__(self, request, user, perms, settings):
        self.request = request
        self.user = user
        self.perms = perms
        self.settings = settings

    @property
    def is_owner(self):
        return self.user and self.user["role"] == "owner"

    def can(self, module, action):
        return bool(self.perms.get(module, {}).get(action))

    def require(self, module, action):
        if not self.can(module, action):
            raise HTTPException(403)

    def require_owner(self):
        if not self.is_owner:
            raise HTTPException(403)

    def audit(self, action, module=None, record_type=None, record_id=None,
              description="", before=None, after=None):
        security.audit(self.user, action, module, record_type, record_id, description,
                       before, after, client_ip(self.request))


def load_user(request):
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not user or not user["active"] or user["session_version"] != request.session.get("sv"):
        request.session.pop("uid", None)
        return None
    login_ts = request.session.get("login_ts", 0)
    if time.time() - login_ts > config.SESSION_HOURS * 3600:
        request.session.pop("uid", None)
        return None
    return user


def ctx(request, allow_password_change=False):
    if not owner_exists():
        raise Redirect("/kreator")
    user = load_user(request)
    if not user:
        nxt = request.url.path
        raise Redirect("/logowanie" + (f"?next={quote(nxt)}" if nxt not in ("/", "/logowanie") else ""))
    if user["must_change_password"] and not allow_password_change:
        raise Redirect("/zmien-haslo")
    settings = db.get_settings()
    if (settings.get("twofa_enabled") == "1" and user["role"] == "owner" and not user["totp_enabled"]
            and not allow_password_change and not request.url.path.startswith("/profil/2fa")):
        raise Redirect("/profil/2fa?wymagane=1")
    return Ctx(request, user, security.load_permissions(user), settings)


async def form_data(request):
    form = await request.form()
    if not security.csrf_valid(request.session, form.get("csrf")):
        raise HTTPException(400, "Sesja formularza wygasła. Odśwież stronę i spróbuj ponownie.")
    return form


def render(request, name, c=None, status=200, **kw):
    if not kw.pop("keep_code", False):
        request.session.pop("show_code", None)  # kod odzyskiwania znika z sesji po opuszczeniu strony z kodem
    flashes = request.session.pop("flash", [])
    context = {
        "user": c.user if c else None,
        "perms": c.perms if c else None,
        "is_owner": c.is_owner if c else False,
        "settings": c.settings if c else db.get_settings(),
        "flashes": flashes,
        "csrf": security.csrf_token(request.session),
        "path": request.url.path,
        "today": date.today().isoformat(),
    }
    context.update(kw)
    return templates.TemplateResponse(request, name, context, status_code=status)


def go(url):
    return RedirectResponse(url, status_code=303)


def module_or_404(module):
    if module not in config.MODULES:
        raise HTTPException(404)
    return config.MODULES[module]


def int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def float_or_none(value):
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


# ======================================================================
#  PLIKI: ZDJĘCIA I ZAŁĄCZNIKI
# ======================================================================

def _ext(filename):
    return Path(filename or "").suffix.lower()


async def store_upload(upload: UploadFile, images_only=False):
    """Zapisuje plik; zwraca (stored_name, size, mime) albo rzuca ValueError."""
    ext = _ext(upload.filename)
    allowed = config.IMAGE_EXTENSIONS if images_only else config.ALLOWED_EXTENSIONS
    if ext not in allowed or ext in files.BLOCKED_EXTENSIONS:
        raise ValueError(f"Niedozwolony typ pliku: {upload.filename}")
    data = await upload.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"Plik {upload.filename} jest większy niż {config.MAX_UPLOAD_MB} MB")
    if not data:
        raise ValueError(f"Plik {upload.filename} jest pusty")
    # Typ ustala serwer po zawartości; typ podany przez przeglądarkę (upload.content_type) jest ignorowany.
    mime = files.check_upload(upload.filename, data, allowed)
    stored = secrets.token_hex(16) + ext
    (config.UPLOAD_DIR / stored).write_bytes(data)
    return stored, len(data), mime


def remove_file(stored_name):
    if stored_name:
        p = config.UPLOAD_DIR / Path(stored_name).name
        p.unlink(missing_ok=True)


async def save_attachments(c: Ctx, form, module, object_id=None, term_id=None):
    errors, saved = [], 0
    for up in form.getlist("files"):
        if not isinstance(up, UploadFile) or not up.filename:
            continue
        try:
            stored, size, mime = await store_upload(up)
        except ValueError as e:
            errors.append(str(e))
            continue
        aid = db.execute(
            """INSERT INTO attachments(module,object_id,term_id,original_name,stored_name,mime,size,uploaded_by,uploaded_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (module, object_id, term_id, Path(up.filename).name, stored, mime, size, c.user["id"], db.now_str()),
        )
        c.audit("upload", module, "załącznik", aid, f"Dodano załącznik {up.filename}")
        saved += 1
    for e in errors:
        flash(c.request, e, "error")
    return saved


def attachments_for(module, object_id=None, term_id=None):
    if term_id:
        rows = db.query("SELECT * FROM attachments WHERE term_id=? ORDER BY uploaded_at DESC", (term_id,))
    else:
        rows = db.query(
            "SELECT * FROM attachments WHERE module=? AND object_id=? AND term_id IS NULL ORDER BY uploaded_at DESC",
            (module, object_id),
        )
    for r in rows:
        r["is_image"] = _ext(r["original_name"]) in config.IMAGE_EXTENSIONS and (r["mime"] or "").startswith("image/")
    return rows


# ======================================================================
#  PWA
# ======================================================================

@app.get("/sw.js")
def service_worker():
    return FileResponse(config.BASE_DIR / "static" / "js" / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest():
    name = db.get_settings().get("company_name") or config.APP_NAME
    data = {
        "name": f"{config.APP_NAME} – {name}" if name != config.APP_NAME else config.APP_NAME,
        "short_name": config.APP_NAME,
        "description": config.APP_TAGLINE,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#F2F5FA",
        "theme_color": "#1F3B70",
        "lang": "pl",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return JSONResponse(data, media_type="application/manifest+json")


@app.get("/offline", response_class=HTMLResponse)
def offline(request: Request):
    return render(request, "offline.html")


# ======================================================================
#  KREATOR PIERWSZEGO URUCHOMIENIA
# ======================================================================

def _setup_step(request):
    if request.session.get("setup_code"):
        return 3
    return 2 if request.session.get("setup_company") else 1


@app.get("/kreator", response_class=HTMLResponse)
def setup_get(request: Request, krok: int = 0):
    if owner_exists() and not request.session.get("setup_code"):
        return go("/logowanie")
    step = _setup_step(request)
    if krok == 1 and step == 2:
        step = 1
    return render(request, "setup.html", step=step, data=request.session.get("setup_company") or {},
                  code=request.session.get("setup_code"), errors=[])


@app.post("/kreator/firma")
async def setup_company(request: Request):
    if owner_exists():
        return go("/logowanie")
    form = await form_data(request)
    name = (form.get("company_name") or "").strip()
    remind = int_or_none(form.get("remind_days")) or 30
    urgent = int_or_none(form.get("urgent_days")) or 7
    errors = []
    if not name:
        errors.append("Podaj nazwę firmy.")
    if not 1 <= remind <= 365:
        errors.append("Okres przypomnień musi mieścić się w zakresie 1–365 dni.")
    if not 0 <= urgent <= remind:
        errors.append("Próg „pilne” nie może być większy niż okres przypomnień.")
    data = {"company_name": name, "remind_days": remind, "urgent_days": urgent}
    if errors:
        return render(request, "setup.html", step=1, data=data, errors=errors)
    request.session["setup_company"] = data
    return go("/kreator")


@app.post("/kreator/wlasciciel")
async def setup_owner(request: Request):
    if owner_exists():
        return go("/logowanie")
    company = request.session.get("setup_company")
    if not company:
        return go("/kreator")
    form = await form_data(request)
    f = {k: (form.get(k) or "").strip() for k in ("full_name", "username", "email", "phone")}
    pw, pw2 = form.get("password") or "", form.get("password2") or ""
    errors = []
    if not f["full_name"]:
        errors.append("Podaj imię i nazwisko właściciela.")
    if len(f["username"]) < 3 or " " in f["username"]:
        errors.append("Login musi mieć co najmniej 3 znaki i nie może zawierać spacji.")
    problems = security.password_problems(pw, f["username"])
    if problems:
        errors.append("Hasło nie spełnia wymagań: " + ", ".join(problems) + ".")
    if pw != pw2:
        errors.append("Hasła nie są takie same.")
    if errors:
        return render(request, "setup.html", step=2, data=company, owner=f, errors=errors)
    code = security.generate_recovery_code()
    with db.tx() as conn:
        for k in ("company_name", "remind_days", "urgent_days"):
            conn.execute("UPDATE settings SET value=? WHERE key=?", (str(company[k]), k))
        cur = conn.execute(
            """INSERT INTO users(username,password_hash,full_name,email,phone,role,is_primary,
                                 recovery_hash,recovery_created_at,created_at)
               VALUES(?,?,?,?,?,'owner',1,?,?,?)""",
            (f["username"], security.hash_password(pw), f["full_name"], f["email"], f["phone"],
             security.hash_recovery_code(code), db.now_str(), db.now_str()),
        )
        uid = cur.lastrowid
    user = db.one("SELECT * FROM users WHERE id=?", (uid,))
    security.audit(user, "setup", None, "system", None, "Kreator: utworzono głównego właściciela i ustawienia firmy",
                   ip=client_ip(request))
    request.session["setup_code"] = code
    request.session["setup_uid"] = uid
    return go("/kreator")


@app.get("/kreator/kod.txt")
def setup_code_file(request: Request):
    code = request.session.get("setup_code")
    if not code:
        raise HTTPException(404)
    return _code_file(code, db.get_settings().get("company_name"))


def _code_file(code, company):
    text = (
        f"{config.APP_NAME} – kod odzyskiwania konta właściciela\r\n"
        f"Firma: {company or ''}\r\n"
        f"Wygenerowano: {datetime.now().strftime('%d.%m.%Y %H:%M')}\r\n\r\n"
        f"KOD: {code}\r\n\r\n"
        "Kod pozwala ustawić nowe hasło, gdy zapomnisz obecnego.\r\n"
        "Przechowuj go w bezpiecznym miejscu, oddzielnie od komputera.\r\n"
        "Po użyciu kodu program wygeneruje nowy.\r\n"
    )
    return Response(text.encode("utf-8"), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="kod-odzyskiwania.txt"'})


@app.post("/kreator/zakoncz")
async def setup_finish(request: Request):
    code = request.session.get("setup_code")
    uid = request.session.get("setup_uid")
    if not code or not uid:
        return go("/logowanie")
    form = await form_data(request)
    if not form.get("saved"):
        return render(request, "setup.html", step=3, code=code, data={},
                      errors=["Potwierdź, że kod odzyskiwania został zapisany."])
    db.set_setting("setup_done", "1")
    user = db.one("SELECT * FROM users WHERE id=?", (uid,))
    for k in ("setup_code", "setup_uid", "setup_company"):
        request.session.pop(k, None)
    _start_session(request, user)
    try:
        svc.create_backup("start")
    except Exception:
        pass
    flash(request, "Program jest gotowy. Dodaj pracowników, pojazdy, maszyny i terminy.")
    return go("/")


# ======================================================================
#  LOGOWANIE
# ======================================================================

def _start_session(request, user):
    csrf = request.session.get("csrf")
    request.session.clear()
    if csrf:
        request.session["csrf"] = csrf
    request.session["uid"] = user["id"]
    request.session["sv"] = user["session_version"]
    request.session["login_ts"] = time.time()
    sessions.rotate(request)
    security.throttle_reset(client_ip(request))
    db.execute("UPDATE users SET last_login=?, failed_attempts=0, locked_until=NULL WHERE id=?",
               (db.now_str(), user["id"]))


def _locked(user):
    """Od wersji 1.0.2 konta nie są blokowane (ograniczenie działa wg adresu IP)."""
    return None


def _register_fail(user, request, reason):
    security.throttle_fail(client_ip(request))
    security.audit(user, "login_failed", None, "konto", user["id"] if user else None, reason, ip=client_ip(request))


def _throttled(request):
    return security.throttle_wait(client_ip(request))


@app.get("/logowanie", response_class=HTMLResponse)
def login_get(request: Request, next: str = "/"):
    if not owner_exists():
        return go("/kreator")
    if load_user(request):
        return go("/")
    return render(request, "login.html", next=safe_back(next, "/"), error=None, insecure=insecure_connection(request))


@app.post("/logowanie")
async def login_post(request: Request):
    form = await form_data(request)
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    nxt = safe_back(form.get("next"), "/")
    insecure = insecure_connection(request)
    wait = _throttled(request)
    if wait:
        return render(request, "login.html", next=nxt, username=username, error=security.wait_message(wait),
                      insecure=insecure)
    user = db.one("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,))
    if not user:
        security.burn_password_check(password)  # ten sam czas odpowiedzi co dla istniejącego loginu
    if not user or not security.verify_password(password, user["password_hash"]):
        _register_fail(user, request, "Nieudane logowanie" + (f": {username[:60]}" if not user else ""))
        return render(request, "login.html", next=nxt, username=username, error="Nieprawidłowy login lub hasło.",
                      insecure=insecure)
    if not user["active"]:
        _register_fail(user, request, "Próba logowania na nieaktywne konto")
        return render(request, "login.html", next=nxt, username=username,
                      error="Konto jest wyłączone. Skontaktuj się z właścicielem.", insecure=insecure)
    if user["totp_enabled"] and user["totp_secret"] and db.get_settings().get("twofa_enabled") == "1":
        request.session["pending_uid"] = user["id"]
        request.session["pending_ts"] = time.time()
        request.session["pending_next"] = nxt
        return go("/logowanie/kod")
    _start_session(request, user)
    security.audit(user, "login", None, "konto", user["id"], "Zalogowano", ip=client_ip(request))
    return go(nxt)


def _pending_user(request):
    uid = request.session.get("pending_uid")
    if not uid or time.time() - request.session.get("pending_ts", 0) > 300:
        request.session.pop("pending_uid", None)
        return None
    return db.one("SELECT * FROM users WHERE id=? AND active=1", (uid,))


@app.get("/logowanie/kod", response_class=HTMLResponse)
def login_code_get(request: Request):
    if not _pending_user(request):
        return go("/logowanie")
    return render(request, "login_code.html", error=None)


@app.post("/logowanie/kod")
async def login_code_post(request: Request):
    form = await form_data(request)
    user = _pending_user(request)
    if not user:
        flash(request, "Minęło zbyt dużo czasu. Zaloguj się ponownie.", "warn")
        return go("/logowanie")
    wait = _throttled(request)
    if wait:
        return render(request, "login_code.html", error=security.wait_message(wait))
    counter = totp.verify(user["totp_secret"], form.get("code"), user["totp_last"])
    if counter is None:
        _register_fail(user, request, "Nieprawidłowy kod logowania dwuetapowego")
        return render(request, "login_code.html", error="Nieprawidłowy kod. Sprawdź, czy czas w telefonie jest ustawiony automatycznie.")
    db.execute("UPDATE users SET totp_last=? WHERE id=?", (counter, user["id"]))
    nxt = safe_back(request.session.get("pending_next"), "/")
    _start_session(request, user)
    security.audit(user, "login", None, "konto", user["id"], "Zalogowano (z kodem dwuetapowym)", ip=client_ip(request))
    return go(nxt)


@app.post("/wyloguj")
async def logout(request: Request):
    await form_data(request)
    user = load_user(request)
    if user:
        security.audit(user, "logout", None, "konto", user["id"], "Wylogowano", ip=client_ip(request))
    request.session.clear()
    sessions.destroy(request)  # sesja znika z serwera – skopiowane ciasteczko przestaje działać
    return go("/logowanie")


@app.get("/odzyskiwanie", response_class=HTMLResponse)
def recovery_get(request: Request):
    return render(request, "recovery.html", error=None, new_code=None)


GENERIC_RECOVERY_ERROR = "Nieprawidłowy login właściciela lub kod odzyskiwania."


@app.post("/odzyskiwanie")
async def recovery_post(request: Request):
    form = await form_data(request)
    username = (form.get("username") or "").strip()
    code = form.get("code") or ""
    pw, pw2 = form.get("password") or "", form.get("password2") or ""
    wait = _throttled(request)
    if wait:
        return render(request, "recovery.html", username=username, new_code=None, error=security.wait_message(wait))
    # Kod działa tylko dla aktywnego właściciela. Wyłączone konto nie wróci samo przez kod odzyskiwania.
    user = db.one("SELECT * FROM users WHERE username=? COLLATE NOCASE AND role='owner' AND active=1", (username,))
    if not user or not user["recovery_hash"]:
        security.burn_password_check(code)
        _register_fail(user, request, "Nieudana próba użycia kodu odzyskiwania")
        return render(request, "recovery.html", username=username, new_code=None, error=GENERIC_RECOVERY_ERROR)
    if not security.verify_recovery_code(code, user["recovery_hash"]):
        _register_fail(user, request, "Nieudana próba użycia kodu odzyskiwania")
        return render(request, "recovery.html", username=username, new_code=None, error=GENERIC_RECOVERY_ERROR)
    problems = security.password_problems(pw, user["username"])
    if problems or pw != pw2:
        msg = ("Hasło nie spełnia wymagań: " + ", ".join(problems) + ".") if problems else "Hasła nie są takie same."
        return render(request, "recovery.html", username=username, new_code=None, error=msg)
    new_code = security.generate_recovery_code()
    db.execute(
        """UPDATE users SET password_hash=?, recovery_hash=?, recovery_created_at=?, must_change_password=0,
                  failed_attempts=0, locked_until=NULL, session_version=session_version+1,
                  totp_enabled=0, totp_secret=NULL, totp_last=NULL WHERE id=?""",
        (security.hash_password(pw), security.hash_recovery_code(new_code), db.now_str(), user["id"]),
    )
    sessions.delete_user_sessions(user["id"])
    security.throttle_reset(client_ip(request))
    security.audit(user, "recovery", None, "konto", user["id"], "Ustawiono nowe hasło kodem odzyskiwania (logowanie dwuetapowe wyłączone – skonfiguruj je ponownie)",
                   ip=client_ip(request))
    _offer_code(request, new_code)
    return render(request, "recovery.html", new_code=new_code, error=None, keep_code=True)


def _offer_code(request, code):
    """Kod do jednorazowego pobrania jako plik .txt – ważny 10 minut i tylko do następnej strony."""
    request.session["show_code"] = {"code": code, "ts": time.time()}


@app.get("/kod-odzyskiwania.txt")
def code_download(request: Request):
    item = request.session.pop("show_code", None)
    if not isinstance(item, dict) or time.time() - item.get("ts", 0) > 600:
        raise HTTPException(404, "Kod można pobrać tylko zaraz po jego wyświetleniu.")
    return _code_file(item["code"], db.get_settings().get("company_name"))


# ======================================================================
#  PROFIL I HASŁO
# ======================================================================

@app.get("/zmien-haslo", response_class=HTMLResponse)
def force_password_get(request: Request):
    c = ctx(request, allow_password_change=True)
    return render(request, "change_password.html", c, errors=[])


@app.post("/zmien-haslo")
async def force_password_post(request: Request):
    c = ctx(request, allow_password_change=True)
    form = await form_data(request)
    errors = _change_password(c, form)
    if errors:
        return render(request, "change_password.html", c, errors=errors)
    flash(request, "Hasło zostało zmienione.")
    return go("/")


def _change_password(c, form):
    current = form.get("current") or ""
    pw, pw2 = form.get("password") or "", form.get("password2") or ""
    errors = []
    if not security.verify_password(current, c.user["password_hash"]):
        errors.append("Obecne hasło jest nieprawidłowe.")
    problems = security.password_problems(pw, c.user["username"])
    if problems:
        errors.append("Nowe hasło nie spełnia wymagań: " + ", ".join(problems) + ".")
    if pw != pw2:
        errors.append("Nowe hasła nie są takie same.")
    if current and pw == current:
        errors.append("Nowe hasło musi różnić się od obecnego.")
    if errors:
        return errors
    db.execute("UPDATE users SET password_hash=?, must_change_password=0, session_version=session_version+1 WHERE id=?",
               (security.hash_password(pw), c.user["id"]))
    # Zmiana hasła wylogowuje wszystkie inne urządzenia; bieżąca sesja dostaje nowy identyfikator.
    sessions.delete_user_sessions(c.user["id"], except_token_hash=c.request.scope.get("nz_session_hash"))
    sessions.rotate(c.request)
    c.audit("password", None, "konto", c.user["id"], "Zmiana własnego hasła (inne urządzenia wylogowane)")
    c.request.session["sv"] = c.user["session_version"] + 1
    return []


@app.get("/profil", response_class=HTMLResponse)
def profile_get(request: Request):
    c = ctx(request)
    emp = db.one("SELECT * FROM employees WHERE id=?", (c.user["employee_id"],)) if c.user["employee_id"] else None
    return render(request, "profile.html", c, errors=[], employee=emp, new_code=None,
                  session_count=sessions.count_user_sessions(c.user["id"]))


@app.post("/profil/wyloguj-wszedzie")
async def logout_everywhere(request: Request):
    c = ctx(request)
    await form_data(request)
    sessions.delete_user_sessions(c.user["id"])
    db.execute("UPDATE users SET session_version=session_version+1 WHERE id=?", (c.user["id"],))
    c.audit("logout", None, "konto", c.user["id"], "Wylogowano na wszystkich urządzeniach")
    request.session.clear()
    sessions.destroy(request)
    flash(request, "Wylogowano na wszystkich urządzeniach.")
    return go("/logowanie")


@app.post("/profil/dane")
async def profile_data(request: Request):
    c = ctx(request)
    form = await form_data(request)
    before = dict(c.user)
    vals = {k: (form.get(k) or "").strip() for k in ("full_name", "email", "phone")}
    channel = form.get("notify_channel") if form.get("notify_channel") in config.USER_CHANNELS else "none"
    db.execute("UPDATE users SET full_name=?, email=?, phone=?, notify_channel=? WHERE id=?",
               (vals["full_name"], vals["email"], vals["phone"], channel, c.user["id"]))
    c.audit("update", None, "konto", c.user["id"], "Zmiana danych własnego konta", before,
            db.one("SELECT * FROM users WHERE id=?", (c.user["id"],)))
    flash(request, "Zapisano dane konta.")
    return go("/profil")


@app.post("/profil/haslo")
async def profile_password(request: Request):
    c = ctx(request)
    form = await form_data(request)
    errors = _change_password(c, form)
    if errors:
        return render(request, "profile.html", c, errors=errors, employee=None, new_code=None,
                      session_count=sessions.count_user_sessions(c.user["id"]))
    flash(request, "Hasło zostało zmienione.")
    return go("/profil")


@app.post("/profil/kod")
async def profile_new_code(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    if not security.verify_password(form.get("current") or "", c.user["password_hash"]):
        return render(request, "profile.html", c, errors=["Aby wygenerować nowy kod, podaj poprawne obecne hasło."],
                      employee=None, new_code=None, session_count=sessions.count_user_sessions(c.user["id"]))
    code = security.generate_recovery_code()
    db.execute("UPDATE users SET recovery_hash=?, recovery_created_at=? WHERE id=?",
               (security.hash_recovery_code(code), db.now_str(), c.user["id"]))
    c.audit("recovery_code", None, "konto", c.user["id"], "Wygenerowano nowy kod odzyskiwania")
    _offer_code(request, code)
    c.user = db.one("SELECT * FROM users WHERE id=?", (c.user["id"],))
    return render(request, "profile.html", c, errors=[], employee=None, new_code=code, keep_code=True,
                  session_count=sessions.count_user_sessions(c.user["id"]))


# ======================================================================
#  PULPIT – PRZYPOMNIENIA
# ======================================================================

def _filtered_terms(c, module=None, view="todo", q="", mine=False, object_id=None):
    where, params = svc.visible_terms_sql(c.user, c.perms)
    sql = f"SELECT * FROM terms WHERE {where}"
    if module:
        sql += " AND module=?"
        params.append(module)
    if object_id:
        sql += " AND object_id=?"
        params.append(object_id)
    if mine:
        own, own_p = svc.own_employee_filter(c.user)
        if own:
            sql += " AND " + own
            params += own_p
        else:
            sql += " AND 0"
    if view == "done":
        sql += " AND status='done' ORDER BY done_date DESC, due_date DESC LIMIT 500"
    else:
        sql += " AND status='open' ORDER BY due_date"
    terms = svc.enrich_terms(db.query(sql, params), c.settings)
    if view == "todo":
        terms = [t for t in terms if t["status_key"] in ("overdue", "urgent", "soon")]
    elif view in ("overdue", "urgent", "soon"):
        terms = [t for t in terms if t["status_key"] == view]
    if q:
        ql = q.lower()
        terms = [t for t in terms if ql in " ".join(str(x or "") for x in (
            t["display_title"], t["object_name"], t["responsible_name"], t.get("notes"),
            t.get("counterparty"), t.get("document_number"))).lower()]
    return terms


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, widok: str = "todo", modul: str = "", q: str = "", moje: int = 0):
    c = ctx(request)
    module = modul if modul in config.MODULES else None
    terms = _filtered_terms(c, module, widok, q.strip(), bool(moje))
    all_open = _filtered_terms(c, None, "all")
    counts = {k: sum(1 for t in all_open if t["status_key"] == k) for k in ("overdue", "urgent", "soon")}
    mine_count = 0
    if c.user["employee_id"]:
        mine_count = sum(1 for t in _filtered_terms(c, None, "todo", mine=True))
    no_code = c.is_owner and not c.user["recovery_hash"]
    visible_modules = [m for m in config.MODULES if c.can(m, "view")]
    return render(request, "dashboard.html", c, terms=terms, counts=counts, view=widok, module=module,
                  q=q, mine=bool(moje), mine_count=mine_count, no_code=no_code,
                  visible_modules=visible_modules)


# ======================================================================
#  MODUŁY – LISTA I KARTA OBIEKTU
# ======================================================================

@app.get("/m/{module}", response_class=HTMLResponse)
def module_list(request: Request, module: str, q: str = "", widok: str = "all"):
    meta = module_or_404(module)
    c = ctx(request)
    c.require(module, "view")
    if not meta["has_objects"]:
        terms = _filtered_terms(c, module, widok if widok in ("all", "todo", "done", "overdue") else "all", q.strip())
        return render(request, "company_list.html", c, module=module, meta=meta, terms=terms, q=q, view=widok)
    objects = svc.all_objects(module)
    terms = svc.enrich_terms(db.query("SELECT * FROM terms WHERE module=? AND status='open'", (module,)), c.settings)
    order = {"overdue": 0, "urgent": 1, "soon": 2, "ok": 3}
    by_obj = {}
    for t in terms:
        by_obj.setdefault(t["object_id"], []).append(t)
    emps = {e["id"]: e for e in svc.employees_brief()}
    rows = []
    for o in objects:
        ts = sorted(by_obj.get(o["id"], []), key=lambda t: (order[t["status_key"]], t["due_date"]))
        o = dict(o)
        o["display"] = svc.object_display(module, o)
        o["open_count"] = len(ts)
        o["next_term"] = ts[0] if ts else None
        o["worst"] = ts[0]["status_key"] if ts else None
        o["responsible"] = emps.get(o.get("responsible_employee_id"))
        rows.append(o)
    if q:
        ql = q.strip().lower()
        rows = [o for o in rows if ql in " ".join(str(o.get(f["name"]) or "") for f in meta["fields"]).lower()
                or ql in o["display"].lower()]
    if widok == "alert":
        rows = [o for o in rows if o["worst"] in ("overdue", "urgent", "soon")]
    return render(request, "module_list.html", c, module=module, meta=meta, rows=rows, q=q, view=widok)


@app.get("/m/{module}/nowy", response_class=HTMLResponse)
def object_new(request: Request, module: str):
    meta = module_or_404(module)
    if not meta["has_objects"]:
        return go(f"/terminy/nowy?modul={module}")
    c = ctx(request)
    c.require(module, "add")
    return render(request, "object_form.html", c, module=module, meta=meta, obj={}, errors=[],
                  custom=svc.custom_fields(module), cvalues={}, employees=svc.employees_brief())


def _parse_object_form(module, meta, form, object_id=None):
    data, errors = {}, []
    for f in meta["fields"]:
        raw = (form.get(f["name"]) or "").strip()
        if f.get("upper"):
            raw = " ".join(raw.upper().split())
        if f["type"] in ("number", "employee"):
            val = int_or_none(raw) if raw else None
            if raw and val is None:
                errors.append(f"Pole „{f['label']}” musi być liczbą.")
        elif f["type"] == "date":
            val = raw if svc.parse_date(raw) else None
        elif f["type"] == "select":
            val = raw if raw in f["options"] else f.get("default")
        else:
            val = raw or None
        if f.get("required") and val in (None, ""):
            errors.append(f"Pole „{f['label']}” jest wymagane.")
        if f["type"] == "email" and val and "@" not in val:
            errors.append("Podaj poprawny adres e-mail.")
        if f.get("unique") and val:
            dup = db.one(f"SELECT id FROM {meta['table']} WHERE {f['name']}=? COLLATE NOCASE AND id<>?",
                         (val, object_id or 0))
            if dup:
                errors.append(f"{f['label']} „{val}” jest już zapisany w innym rekordzie.")
        data[f["name"]] = val
    cvals = {}
    for cf in svc.custom_fields(module):
        raw = (form.get(f"cf_{cf['id']}") or "").strip()
        if cf["field_type"] == "number" and raw and float_or_none(raw) is None:
            errors.append(f"Pole „{cf['name']}” musi być liczbą.")
        if cf["field_type"] == "date" and raw and not svc.parse_date(raw):
            errors.append(f"Pole „{cf['name']}” musi być datą.")
        if cf["required"] and not raw:
            errors.append(f"Pole „{cf['name']}” jest wymagane.")
        cvals[cf["id"]] = raw
    return data, cvals, errors


async def _handle_photo(form, current=None):
    up = form.get("photo")
    if form.get("remove_photo"):
        remove_file(current)
        current = None
    if isinstance(up, UploadFile) and up.filename:
        stored, _, _ = await store_upload(up, images_only=True)
        remove_file(current)
        current = stored
    return current


@app.post("/m/{module}/nowy")
async def object_create(request: Request, module: str):
    meta = module_or_404(module)
    c = ctx(request)
    c.require(module, "add")
    form = await form_data(request)
    data, cvals, errors = _parse_object_form(module, meta, form)
    photo = None
    if not errors:
        try:
            photo = await _handle_photo(form)
        except ValueError as e:
            errors.append(str(e))
    if errors:
        return render(request, "object_form.html", c, module=module, meta=meta, obj=data, errors=errors,
                      custom=svc.custom_fields(module), cvalues=cvals, employees=svc.employees_brief())
    cols = list(data) + ["photo_path", "created_at", "updated_at"]
    vals = list(data.values()) + [photo, db.now_str(), db.now_str()]
    with db.tx() as conn:
        cur = conn.execute(f"INSERT INTO {meta['table']}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
        oid = cur.lastrowid
        svc.save_custom_values(conn, module, oid, cvals)
    obj = svc.get_object(module, oid)
    c.audit("create", module, meta["single"].lower(), oid, f"Dodano: {svc.object_display(module, obj)}", None, obj)
    flash(request, f"Dodano: {svc.object_display(module, obj)}.")
    return go(f"/m/{module}/{oid}")


@app.get("/m/{module}/{oid}", response_class=HTMLResponse)
def object_detail(request: Request, module: str, oid: int, historia: int = 0):
    meta = module_or_404(module)
    c = ctx(request)
    obj = svc.get_object(module, oid)
    if not obj:
        raise HTTPException(404)
    own = module == "employees" and c.user["employee_id"] == oid
    if not c.can(module, "view") and not own:
        raise HTTPException(403)
    rows = db.query("SELECT * FROM terms WHERE module=? AND object_id=? ORDER BY status, due_date", (module, oid))
    terms = svc.enrich_terms(rows, c.settings)
    open_terms = [t for t in terms if t["status"] == "open"]
    done_terms = sorted([t for t in terms if t["status"] == "done"], key=lambda t: t["done_date"] or "", reverse=True)
    resp = None
    if obj.get("responsible_employee_id"):
        resp = db.one("SELECT * FROM employees WHERE id=?", (obj["responsible_employee_id"],))
    extra = {}
    if module == "employees":
        extra["vehicles"] = db.query("SELECT * FROM vehicles WHERE responsible_employee_id=? ORDER BY name", (oid,))
        extra["machines"] = db.query("SELECT * FROM machines WHERE responsible_employee_id=? ORDER BY name", (oid,))
        extra["account"] = db.one("SELECT id, username FROM users WHERE employee_id=?", (oid,))
    return render(request, "object_detail.html", c, module=module, meta=meta, obj=obj,
                  title=svc.object_display(module, obj), open_terms=open_terms, done_terms=done_terms,
                  custom=svc.custom_fields(module), cvalues=svc.custom_values(module, oid),
                  attachments=attachments_for(module, oid), responsible=resp, extra=extra, own=own)


@app.get("/m/{module}/{oid}/edycja", response_class=HTMLResponse)
def object_edit(request: Request, module: str, oid: int):
    meta = module_or_404(module)
    c = ctx(request)
    c.require(module, "edit")
    obj = svc.get_object(module, oid)
    if not obj:
        raise HTTPException(404)
    return render(request, "object_form.html", c, module=module, meta=meta, obj=obj, errors=[],
                  custom=svc.custom_fields(module), cvalues=svc.custom_values(module, oid),
                  employees=svc.employees_brief())


@app.post("/m/{module}/{oid}/edycja")
async def object_update(request: Request, module: str, oid: int):
    meta = module_or_404(module)
    c = ctx(request)
    c.require(module, "edit")
    before = svc.get_object(module, oid)
    if not before:
        raise HTTPException(404)
    form = await form_data(request)
    data, cvals, errors = _parse_object_form(module, meta, form, oid)
    photo = before.get("photo_path")
    if not errors:
        try:
            photo = await _handle_photo(form, photo)
        except ValueError as e:
            errors.append(str(e))
    if errors:
        obj = dict(before)
        obj.update(data)
        return render(request, "object_form.html", c, module=module, meta=meta, obj=obj, errors=errors,
                      custom=svc.custom_fields(module), cvalues=cvals, employees=svc.employees_brief())
    before_cv = svc.custom_values(module, oid)
    sets = ", ".join(f"{k}=?" for k in data) + ", photo_path=?, updated_at=?"
    with db.tx() as conn:
        conn.execute(f"UPDATE {meta['table']} SET {sets} WHERE id=?",
                     list(data.values()) + [photo, db.now_str(), oid])
        svc.save_custom_values(conn, module, oid, cvals)
    after = svc.get_object(module, oid)
    names = {cf["id"]: cf["name"] for cf in svc.custom_fields(module)}
    b = dict(before)
    a = dict(after)
    for fid, name in names.items():
        b["pole: " + name] = before_cv.get(fid, "")
        a["pole: " + name] = cvals.get(fid, "")
    c.audit("update", module, meta["single"].lower(), oid, f"Zmieniono: {svc.object_display(module, after)}", b, a)
    flash(request, "Zapisano zmiany.")
    return go(f"/m/{module}/{oid}")


@app.post("/m/{module}/{oid}/usun")
async def object_delete(request: Request, module: str, oid: int):
    meta = module_or_404(module)
    c = ctx(request)
    c.require(module, "delete")
    await form_data(request)
    obj = svc.get_object(module, oid)
    if not obj:
        raise HTTPException(404)
    files = db.query("SELECT stored_name FROM attachments WHERE module=? AND (object_id=? OR term_id IN "
                     "(SELECT id FROM terms WHERE module=? AND object_id=?))", (module, oid, module, oid))
    n_terms = db.one("SELECT COUNT(*) n FROM terms WHERE module=? AND object_id=?", (module, oid))["n"]
    with db.tx() as conn:
        conn.execute("DELETE FROM attachments WHERE term_id IN (SELECT id FROM terms WHERE module=? AND object_id=?)", (module, oid))
        conn.execute("DELETE FROM attachments WHERE module=? AND object_id=?", (module, oid))
        conn.execute("DELETE FROM terms WHERE module=? AND object_id=?", (module, oid))
        conn.execute("DELETE FROM custom_values WHERE module=? AND object_id=?", (module, oid))
        conn.execute(f"DELETE FROM {meta['table']} WHERE id=?", (oid,))
    for f in files:
        remove_file(f["stored_name"])
    remove_file(obj.get("photo_path"))
    c.audit("delete", module, meta["single"].lower(), oid,
            f"Usunięto: {svc.object_display(module, obj)} (terminów: {n_terms}, plików: {len(files)})", obj, None)
    flash(request, f"Usunięto: {svc.object_display(module, obj)}.")
    return go(f"/m/{module}")


@app.get("/zdjecie/{module}/{oid}")
def object_photo(request: Request, module: str, oid: int):
    module_or_404(module)
    c = ctx(request)
    own = module == "employees" and c.user["employee_id"] == oid
    if not c.can(module, "view") and not own:
        raise HTTPException(403)
    obj = svc.get_object(module, oid)
    if not obj or not obj.get("photo_path"):
        raise HTTPException(404)
    p = config.UPLOAD_DIR / Path(obj["photo_path"]).name
    if not p.exists():
        raise HTTPException(404)
    mime, inline = files.serve_info(p, p.name)
    if not mime.startswith("image/"):
        mime, inline = "application/octet-stream", False
    return FileResponse(p, media_type=mime, headers=files.file_headers(mime, inline, "zdjecie" + p.suffix, quote))


# ======================================================================
#  TERMINY
# ======================================================================

def _term_or_404(c, tid, action="view"):
    t = db.one("SELECT * FROM terms WHERE id=?", (tid,))
    if not t:
        raise HTTPException(404)
    if action == "view":
        if not svc.can_see_term(c.user, c.perms, t):
            raise HTTPException(403)
    else:
        c.require(t["module"], action)
    return t


def _term_form_ctx(c, module, term, errors, objects=None):
    return dict(
        module=module, meta=config.MODULES[module], term=term, errors=errors,
        cats=svc.categories(module), employees=svc.employees_brief(),
        objects=[{"id": o["id"], "display": svc.object_display(module, o),
                  "resp": svc.default_responsible(module, o["id"])}
                 for o in (svc.all_objects(module) if config.MODULES[module]["has_objects"] else [])],
    )


@app.get("/terminy/nowy", response_class=HTMLResponse)
def term_new(request: Request, modul: str = "", obiekt: int = 0):
    c = ctx(request)
    if modul not in config.MODULES:
        allowed = [m for m in config.MODULES if c.can(m, "add")]
        if not allowed:
            raise HTTPException(403)
        return render(request, "term_pick.html", c, allowed=allowed)
    c.require(modul, "add")
    term = {"object_id": obiekt or None, "responsible_employee_id": svc.default_responsible(modul, obiekt) if obiekt else None}
    return render(request, "term_form.html", c, **_term_form_ctx(c, modul, term, []))


def _parse_term_form(module, form):
    meta = config.MODULES[module]
    errors = []
    category = (form.get("category") or "").strip()
    if category == "__new__":
        category = (form.get("category_new") or "").strip()
    t = {
        "category": category,
        "title": (form.get("title") or "").strip() or None,
        "due_date": (form.get("due_date") or "").strip(),
        "object_id": int_or_none(form.get("object_id")) if meta["has_objects"] else None,
        "interval_value": int_or_none(form.get("interval_value")) if form.get("recurring") else None,
        "interval_unit": form.get("interval_unit") if form.get("recurring") else None,
        "remind_days": int_or_none(form.get("remind_days")),
        "responsible_employee_id": int_or_none(form.get("responsible_employee_id")),
        "counterparty": (form.get("counterparty") or "").strip() or None,
        "amount": float_or_none(form.get("amount")) if (form.get("amount") or "").strip() else None,
        "document_number": (form.get("document_number") or "").strip() or None,
        "notes": (form.get("notes") or "").strip() or None,
    }
    if not t["category"]:
        errors.append("Wybierz rodzaj sprawy.")
    if not svc.parse_date(t["due_date"]):
        errors.append("Podaj poprawną datę terminu.")
    if meta["has_objects"]:
        if not t["object_id"] or not svc.get_object(module, t["object_id"]):
            errors.append(f"Wybierz: {meta['single'].lower()}.")
    if form.get("recurring"):
        if not t["interval_value"] or t["interval_value"] < 1 or t["interval_unit"] not in config.INTERVAL_UNITS:
            errors.append("Podaj, co ile powtarza się termin (liczba większa od zera).")
    if t["remind_days"] is not None and not 0 <= t["remind_days"] <= 365:
        errors.append("Własny okres przypomnienia musi mieścić się w zakresie 0–365 dni.")
    if (form.get("amount") or "").strip() and t["amount"] is None:
        errors.append("Kwota musi być liczbą.")
    return t, errors


@app.post("/terminy/nowy")
async def term_create(request: Request):
    c = ctx(request)
    form = await form_data(request)
    module = form.get("module")
    module_or_404(module)
    c.require(module, "add")
    t, errors = _parse_term_form(module, form)
    if errors:
        return render(request, "term_form.html", c, **_term_form_ctx(c, module, t, errors))
    if form.get("category") == "__new__" and c.is_owner:
        db.execute("INSERT OR IGNORE INTO categories(module,name,interval_value,interval_unit,sort) VALUES(?,?,?,?,99)",
                   (module, t["category"], t["interval_value"], t["interval_unit"]))
    t.update(module=module, status="open", created_by=c.user["id"], created_at=db.now_str(), updated_at=db.now_str())
    cols = list(t)
    tid = db.execute(f"INSERT INTO terms({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(t.values()))
    await save_attachments(c, form, module, t["object_id"], tid)
    term = svc.enrich_terms([db.one("SELECT * FROM terms WHERE id=?", (tid,))], c.settings)[0]
    c.audit("create", module, "termin", tid, f"Dodano termin: {term['display_title']} – {term['object_name']} ({svc.fmt_date(term['due_date'])})",
            None, db.one("SELECT * FROM terms WHERE id=?", (tid,)))
    flash(request, "Dodano termin.")
    return go(safe_back(form.get("back"), f"/terminy/{tid}"))


@app.get("/terminy/{tid}", response_class=HTMLResponse)
def term_detail(request: Request, tid: int):
    c = ctx(request)
    t = _term_or_404(c, tid)
    term = svc.enrich_terms([t], c.settings)[0]
    history = []
    if term["module"] in config.OBJECT_MODULES:
        history = db.query("SELECT * FROM terms WHERE module=? AND object_id=? AND category=? AND id<>? ORDER BY due_date DESC",
                           (t["module"], t["object_id"], t["category"], tid))
    else:
        history = db.query("SELECT * FROM terms WHERE module='company' AND category=? AND COALESCE(counterparty,'')=COALESCE(?,'') AND id<>? ORDER BY due_date DESC LIMIT 30",
                           (t["category"], t["counterparty"], tid))
    history = svc.enrich_terms(history, c.settings)
    return render(request, "term_detail.html", c, term=term, history=history,
                  attachments=attachments_for(t["module"], term_id=tid),
                  creator=db.one("SELECT username, full_name FROM users WHERE id=?", (t["created_by"],)) if t["created_by"] else None,
                  doer=db.one("SELECT username, full_name FROM users WHERE id=?", (t["done_by"],)) if t["done_by"] else None)


@app.get("/terminy/{tid}/edycja", response_class=HTMLResponse)
def term_edit(request: Request, tid: int):
    c = ctx(request)
    t = _term_or_404(c, tid, "edit")
    if t["interval_value"]:
        t["recurring"] = True
    return render(request, "term_form.html", c, **_term_form_ctx(c, t["module"], t, []))


@app.post("/terminy/{tid}/edycja")
async def term_update(request: Request, tid: int):
    c = ctx(request)
    before = _term_or_404(c, tid, "edit")
    form = await form_data(request)
    module = before["module"]
    t, errors = _parse_term_form(module, form)
    if errors:
        t["id"] = tid
        return render(request, "term_form.html", c, **_term_form_ctx(c, module, t, errors))
    t["updated_at"] = db.now_str()
    db.execute(f"UPDATE terms SET {', '.join(k + '=?' for k in t)} WHERE id=?", list(t.values()) + [tid])
    await save_attachments(c, form, module, t["object_id"], tid)
    after = db.one("SELECT * FROM terms WHERE id=?", (tid,))
    e = svc.enrich_terms([after], c.settings)[0]
    c.audit("update", module, "termin", tid, f"Zmieniono termin: {e['display_title']} – {e['object_name']}", before, after)
    flash(request, "Zapisano zmiany terminu.")
    return go(f"/terminy/{tid}")


@app.post("/terminy/{tid}/usun")
async def term_delete(request: Request, tid: int):
    c = ctx(request)
    t = _term_or_404(c, tid, "delete")
    form = await form_data(request)
    e = svc.enrich_terms([t], c.settings)[0]
    files = db.query("SELECT stored_name FROM attachments WHERE term_id=?", (tid,))
    with db.tx() as conn:
        conn.execute("DELETE FROM attachments WHERE term_id=?", (tid,))
        conn.execute("DELETE FROM terms WHERE id=?", (tid,))
    for f in files:
        remove_file(f["stored_name"])
    c.audit("delete", t["module"], "termin", tid, f"Usunięto termin: {e['display_title']} – {e['object_name']}", t, None)
    flash(request, "Usunięto termin.")
    back = safe_back(form.get("back"), f"/m/{t['module']}/{t['object_id']}" if t["object_id"] else f"/m/{t['module']}")
    return go(back)


@app.get("/terminy/{tid}/wykonane", response_class=HTMLResponse)
def term_done_get(request: Request, tid: int):
    c = ctx(request)
    t = _term_or_404(c, tid, "edit")
    if t["status"] == "done":
        return go(f"/terminy/{tid}")
    term = svc.enrich_terms([t], c.settings)[0]
    today = date.today()
    base = svc.parse_date(t["due_date"]) if t["module"] == "company" else today
    nxt = svc.add_interval(base, t["interval_value"], t["interval_unit"]) if term["recurring"] else None
    return render(request, "term_done.html", c, term=term, next_date=nxt.isoformat() if nxt else "",
                  base_mode="due" if t["module"] == "company" else "done", errors=[])


@app.post("/terminy/{tid}/wykonane")
async def term_done_post(request: Request, tid: int):
    c = ctx(request)
    t = _term_or_404(c, tid, "edit")
    form = await form_data(request)
    done_date = (form.get("done_date") or "").strip()
    note = (form.get("done_note") or "").strip() or None
    term = svc.enrich_terms([t], c.settings)[0]
    errors = []
    if not svc.parse_date(done_date):
        errors.append("Podaj datę wykonania.")
    next_date = (form.get("next_date") or "").strip()
    plan_next = bool(form.get("plan_next"))
    if plan_next and not svc.parse_date(next_date):
        errors.append("Podaj datę kolejnego terminu.")
    if errors:
        return render(request, "term_done.html", c, term=term, next_date=next_date, base_mode="done", errors=errors)
    with db.tx() as conn:
        conn.execute("UPDATE terms SET status='done', done_date=?, done_note=?, done_by=?, updated_at=? WHERE id=?",
                     (done_date, note, c.user["id"], db.now_str(), tid))
        new_id = None
        if plan_next:
            copy = {k: t[k] for k in ("module", "object_id", "category", "title", "interval_value", "interval_unit",
                                      "remind_days", "responsible_employee_id", "counterparty", "amount",
                                      "document_number", "notes")}
            copy.update(due_date=next_date, status="open", previous_id=tid, created_by=c.user["id"],
                        created_at=db.now_str(), updated_at=db.now_str())
            cols = list(copy)
            new_id = conn.execute(f"INSERT INTO terms({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                                  list(copy.values())).lastrowid
    await save_attachments(c, form, t["module"], t["object_id"], tid)
    desc = f"Wykonano: {term['display_title']} – {term['object_name']} ({svc.fmt_date(done_date)})"
    if new_id:
        desc += f"; zaplanowano kolejny na {svc.fmt_date(next_date)}"
    c.audit("done", t["module"], "termin", tid, desc, t, db.one("SELECT * FROM terms WHERE id=?", (tid,)))
    flash(request, "Oznaczono jako wykonane." + (f" Kolejny termin: {svc.fmt_date(next_date)}." if new_id else ""))
    return go(f"/terminy/{new_id or tid}")


@app.post("/terminy/{tid}/przywroc")
async def term_reopen(request: Request, tid: int):
    c = ctx(request)
    t = _term_or_404(c, tid, "edit")
    await form_data(request)
    db.execute("UPDATE terms SET status='open', done_date=NULL, done_note=NULL, done_by=NULL, updated_at=? WHERE id=?",
               (db.now_str(), tid))
    e = svc.enrich_terms([t], c.settings)[0]
    c.audit("reopen", t["module"], "termin", tid, f"Cofnięto wykonanie: {e['display_title']} – {e['object_name']}", t,
            db.one("SELECT * FROM terms WHERE id=?", (tid,)))
    flash(request, "Termin ponownie jest otwarty. Jeśli program zaplanował już kolejny termin, sprawdź go lub usuń.", "warn")
    return go(f"/terminy/{tid}")


# ======================================================================
#  ZAŁĄCZNIKI
# ======================================================================

@app.post("/zalaczniki")
async def attachment_upload(request: Request):
    c = ctx(request)
    form = await form_data(request)
    module = form.get("module")
    module_or_404(module)
    term_id = int_or_none(form.get("term_id"))
    object_id = int_or_none(form.get("object_id"))
    if term_id:
        t = _term_or_404(c, term_id, "edit")
        module, object_id = t["module"], t["object_id"]
    else:
        c.require(module, "edit")
        if not svc.get_object(module, object_id):
            raise HTTPException(404)
    n = await save_attachments(c, form, module, object_id, term_id)
    if n:
        flash(request, f"Dodano plików: {n}.")
    return go(safe_back(form.get("back"), "/"))


def _attachment_access(c, a, action="view"):
    if a["term_id"]:
        _term_or_404(c, a["term_id"], action)
    else:
        own = a["module"] == "employees" and c.user["employee_id"] == a["object_id"]
        if action == "view" and own:
            return
        c.require(a["module"], action)


@app.get("/zalaczniki/{aid}")
def attachment_get(request: Request, aid: int, pobierz: int = 0):
    c = ctx(request)
    a = db.one("SELECT * FROM attachments WHERE id=?", (aid,))
    if not a:
        raise HTTPException(404)
    _attachment_access(c, a)
    p = config.UPLOAD_DIR / Path(a["stored_name"]).name
    if not p.exists():
        raise HTTPException(404, "Plik nie istnieje na serwerze.")
    # Typ i sposób otwarcia ustala serwer (rozszerzenie + zawartość), nigdy typ zapisany przy wysyłce.
    mime, inline = files.serve_info(p, a["original_name"])
    inline = inline and not pobierz
    return FileResponse(p, media_type=mime, headers=files.file_headers(mime, inline, a["original_name"], quote))


@app.post("/zalaczniki/{aid}/usun")
async def attachment_delete(request: Request, aid: int):
    c = ctx(request)
    form = await form_data(request)
    a = db.one("SELECT * FROM attachments WHERE id=?", (aid,))
    if not a:
        raise HTTPException(404)
    _attachment_access(c, a, "delete")
    db.execute("DELETE FROM attachments WHERE id=?", (aid,))
    remove_file(a["stored_name"])
    c.audit("delete", a["module"], "załącznik", aid, f"Usunięto załącznik {a['original_name']}", a, None)
    flash(request, "Usunięto plik.")
    return go(safe_back(form.get("back"), "/"))


# ======================================================================
#  POWIADOMIENIA (RĘCZNE SMS / E-MAIL)
# ======================================================================

@app.get("/api/terminy/{tid}/powiadomienie")
def notify_data(request: Request, tid: int):
    c = ctx(request)
    t = _term_or_404(c, tid)
    if not c.can(t["module"], "notify"):
        raise HTTPException(403, "Brak uprawnienia do powiadamiania w tym module.")
    term = svc.enrich_terms([t], c.settings)[0]
    contacts = []
    # Pełna lista kontaktów tylko dla osób, które i tak widzą kartotekę pracowników;
    # pozostali dostają wyłącznie osobę odpowiedzialną za ten termin.
    full_list = c.is_owner or c.can("employees", "view")
    for e in svc.employees_brief():
        if not full_list and e["id"] != t["responsible_employee_id"]:
            continue
        if e["phone"] or e["email"]:
            contacts.append({"key": f"e{e['id']}", "name": f"{e['first_name']} {e['last_name']}",
                             "info": e["position"] or "pracownik", "phone": svc.normalize_phone(e["phone"]),
                             "email": e["email"] or "", "default": e["id"] == t["responsible_employee_id"]})
    for u in db.query("SELECT id, username, full_name, phone, email, employee_id FROM users WHERE active=1"):
        if full_list and (u["phone"] or u["email"]) and not u["employee_id"]:
            contacts.append({"key": f"u{u['id']}", "name": u["full_name"] or u["username"], "info": "użytkownik programu",
                             "phone": svc.normalize_phone(u["phone"]), "email": u["email"] or "", "default": False})
    s = c.settings
    first = next((x for x in contacts if x["default"]), contacts[0] if contacts else None)
    first_name = (first["name"].split(" ")[0] if first else "")
    return {
        "term": {"id": tid, "title": term["display_title"], "object": term["object_name"],
                 "due": svc.fmt_date(term["due_date"]), "left": term["left_label"]},
        "contacts": contacts,
        "sms": svc.render_template(s.get("template_sms"), term, s, c.user, "{osoba}"),
        "email_subject": svc.render_template(s.get("template_email_subject"), term, s, c.user, "{osoba}"),
        "email_body": svc.render_template(s.get("template_email_body"), term, s, c.user, "{osoba}"),
        "default_first_name": first_name,
    }


@app.post("/api/powiadomienie")
async def notify_log(request: Request):
    c = ctx(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400)
    if not security.csrf_valid(request.session, data.get("csrf")):
        raise HTTPException(400)
    t = _term_or_404(c, int_or_none(data.get("term_id")) or 0)
    if not c.can(t["module"], "notify"):
        raise HTTPException(403)
    channel = "SMS" if data.get("channel") == "sms" else "e-mail"
    term = svc.enrich_terms([t], c.settings)[0]
    recipient = str(data.get("recipient") or "")[:120]
    address = str(data.get("address") or "")[:120]
    c.audit("notify", t["module"], "termin", t["id"],
            f"Powiadomienie {channel} do: {recipient} ({address}) – {term['display_title']}, {term['object_name']}",
            None, {"kanał": channel, "odbiorca": recipient, "adres": address, "treść": str(data.get("text") or "")[:1000]})
    return {"ok": True}


# ======================================================================
#  EKSPORT
# ======================================================================

def _export_response(fmt, filename, title, headers, rows):
    if fmt == "xlsx":
        body = svc.to_xlsx(title, headers, rows)
        mt = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        body = svc.to_csv(headers, rows)
        mt = "text/csv; charset=utf-8"
    stamp = date.today().isoformat()
    return Response(body, media_type=mt,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'{filename}-{stamp}.{fmt}')}"})


@app.get("/eksport/terminy.{fmt}")
def export_terms(request: Request, fmt: str, widok: str = "all", modul: str = "", q: str = "", moje: int = 0):
    c = ctx(request)
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(404)
    module = modul if modul in config.MODULES else None
    if module:
        c.require(module, "view")
    terms = _filtered_terms(c, module, widok, q.strip(), bool(moje))
    headers = ["Moduł", "Dotyczy", "Sprawa", "Termin", "Status", "Pozostało", "Odpowiedzialny",
               "Cykl", "Kontrahent", "Kwota", "Nr dokumentu", "Wykonano", "Uwagi"]
    rows = [[config.MODULES[t["module"]]["label"], t["object_name"], t["display_title"], svc.fmt_date(t["due_date"]),
             t["status_label"], t["left_label"], t["responsible_name"],
             f"co {t['interval_value']} {config.INTERVAL_UNITS.get(t['interval_unit'], '')}" if t["recurring"] else "",
             t.get("counterparty"), t.get("amount"), t.get("document_number"),
             svc.fmt_date(t["done_date"]) if t["done_date"] else "", t.get("notes")] for t in terms]
    c.audit("export", module, "terminy", None, f"Eksport terminów ({fmt}, {len(rows)} wierszy)")
    return _export_response(fmt, "terminy", "Terminy", headers, rows)


@app.get("/eksport/m/{module}.{fmt}")
def export_module(request: Request, module: str, fmt: str):
    meta = module_or_404(module)
    c = ctx(request)
    c.require(module, "view")
    if fmt not in ("csv", "xlsx") or not meta["has_objects"]:
        raise HTTPException(404)
    emps = {e["id"]: f"{e['first_name']} {e['last_name']}" for e in svc.employees_brief()}
    cfs = svc.custom_fields(module)
    headers = [f["label"] for f in meta["fields"]] + [cf["name"] for cf in cfs]
    rows = []
    for o in svc.all_objects(module):
        cv = svc.custom_values(module, o["id"])
        row = []
        for f in meta["fields"]:
            v = o.get(f["name"])
            if f["type"] == "employee":
                v = emps.get(v, "")
            elif f["type"] == "date":
                v = svc.fmt_date(v) if v else ""
            elif f["type"] == "select":
                v = f["options"].get(v or f.get("default"), "")
            row.append(v)
        row += [cv.get(cf["id"], "") for cf in cfs]
        rows.append(row)
    c.audit("export", module, meta["label"].lower(), None, f"Eksport: {meta['label']} ({fmt}, {len(rows)} wierszy)")
    return _export_response(fmt, meta["label"].lower(), meta["label"], headers, rows)


# ======================================================================
#  PANEL WŁAŚCICIELA
# ======================================================================

@app.get("/panel", response_class=HTMLResponse)
def panel(request: Request):
    c = ctx(request)
    c.require_owner()
    stats = {
        "users": db.one("SELECT COUNT(*) n FROM users")["n"],
        "employees": db.one("SELECT COUNT(*) n FROM employees")["n"],
        "vehicles": db.one("SELECT COUNT(*) n FROM vehicles")["n"],
        "machines": db.one("SELECT COUNT(*) n FROM machines")["n"],
        "terms": db.one("SELECT COUNT(*) n FROM terms WHERE status='open'")["n"],
        "log": db.one("SELECT COUNT(*) n FROM audit_log")["n"],
    }
    backups = svc.list_backups()
    return render(request, "panel/index.html", c, stats=stats, last_backup=backups[0] if backups else None,
                  insecure=insecure_connection(request), portable=config.PORTABLE, data_dir=str(config.DATA_DIR))


# ---------- Użytkownicy ----------

@app.get("/panel/uzytkownicy", response_class=HTMLResponse)
def users_list(request: Request):
    c = ctx(request)
    c.require_owner()
    users = db.query("""SELECT u.*, e.first_name || ' ' || e.last_name AS employee_name
                        FROM users u LEFT JOIN employees e ON e.id=u.employee_id
                        ORDER BY u.role DESC, u.username""")
    for u in users:
        u["perms"] = security.load_permissions(u)
        u["locked"] = bool(_locked(u))
    return render(request, "panel/users.html", c, users=users)


def _user_form_ctx(c, u, errors, perms=None):
    return dict(u=u, errors=errors, employees=svc.employees_brief(),
                uperms=perms if perms is not None else (security.load_permissions(u) if u.get("id") else
                                                        {m: {a: False for a in config.ACTIONS} for m in config.MODULES}))


def _parse_user_form(form, uid=None):
    u = {k: (form.get(k) or "").strip() for k in ("username", "full_name", "email", "phone")}
    u["role"] = "owner" if form.get("role") == "owner" else "user"
    u["employee_id"] = int_or_none(form.get("employee_id"))
    u["active"] = 1 if form.get("active") else 0
    u["notify_channel"] = form.get("notify_channel") if form.get("notify_channel") in config.USER_CHANNELS else "none"
    errors = []
    if len(u["username"]) < 3 or " " in u["username"]:
        errors.append("Login musi mieć co najmniej 3 znaki i nie może zawierać spacji.")
    elif db.one("SELECT id FROM users WHERE username=? COLLATE NOCASE AND id<>?", (u["username"], uid or 0)):
        errors.append("Taki login już istnieje.")
    if u["email"] and "@" not in u["email"]:
        errors.append("Podaj poprawny adres e-mail.")
    if u["employee_id"] and db.one("SELECT id FROM users WHERE employee_id=? AND id<>?", (u["employee_id"], uid or 0)):
        errors.append("Ten pracownik ma już przypisane inne konto.")
    perms = {m: {a: bool(form.get(f"p_{m}_{a}")) for a in config.ACTIONS} for m in config.MODULES}
    for m in perms:
        if any(perms[m].values()):
            perms[m]["view"] = True
    return u, perms, errors


@app.get("/panel/uzytkownicy/nowy", response_class=HTMLResponse)
def user_new(request: Request):
    c = ctx(request)
    c.require_owner()
    return render(request, "panel/user_form.html", c, **_user_form_ctx(c, {"active": 1, "role": "user"}, []))


@app.post("/panel/uzytkownicy/nowy")
async def user_create(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    u, perms, errors = _parse_user_form(form)
    pw = form.get("password") or ""
    if pw:
        problems = security.password_problems(pw, u["username"])
        if problems:
            errors.append("Hasło nie spełnia wymagań: " + ", ".join(problems) + ".")
    else:
        pw = security.generate_temp_password()
    if errors:
        return render(request, "panel/user_form.html", c, **_user_form_ctx(c, u, errors, perms))
    uid = db.execute(
        """INSERT INTO users(username,password_hash,full_name,email,phone,role,employee_id,active,notify_channel,
                             must_change_password,created_at) VALUES(?,?,?,?,?,?,?,?,?,1,?)""",
        (u["username"], security.hash_password(pw), u["full_name"], u["email"], u["phone"], u["role"],
         u["employee_id"], u["active"], u["notify_channel"], db.now_str()),
    )
    if u["role"] == "user":
        security.save_permissions(uid, perms)
    created = db.one("SELECT * FROM users WHERE id=?", (uid,))
    after = dict(created)
    after["uprawnienia"] = _perm_summary(perms) if u["role"] == "user" else "właściciel – pełny dostęp"
    c.audit("create", None, "konto", uid, f"Dodano konto {u['username']} ({'właściciel' if u['role'] == 'owner' else 'użytkownik'})", None, after)
    return render(request, "panel/temp_password.html", c, target=created, password=pw, created=True)


def _perm_summary(perms):
    parts = []
    for m, acts in perms.items():
        on = [config.ACTIONS[a].lower() for a, v in acts.items() if v]
        if on:
            parts.append(f"{config.MODULES[m]['label']}: {', '.join(on)}")
    return "; ".join(parts) or "brak"


@app.get("/panel/uzytkownicy/{uid}", response_class=HTMLResponse)
def user_edit(request: Request, uid: int):
    c = ctx(request)
    c.require_owner()
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise HTTPException(404)
    u["locked"] = bool(_locked(u))
    return render(request, "panel/user_form.html", c, **_user_form_ctx(c, u, []),
                  protected=_primary_protected(c, u), session_count=sessions.count_user_sessions(uid))


def _primary_protected(c, target):
    """Konto głównego właściciela edytowane przez innego właściciela – hasło, 2FA, login i e-mail są chronione."""
    return bool(target["is_primary"]) and target["id"] != c.user["id"]


def _owner_guard(c, target, new_role=None, new_active=None, deleting=False):
    """Zasady bezpieczeństwa dla kont właścicieli."""
    errors = []
    is_self = target["id"] == c.user["id"]
    demote = target["role"] == "owner" and new_role == "user"
    deactivate = target["active"] and new_active == 0
    if target["is_primary"] and (demote or deactivate or deleting):
        errors.append("Głównego właściciela nie można usunąć, wyłączyć ani zmienić mu roli.")
    if is_self and (demote or deactivate or deleting):
        errors.append("Nie możesz usunąć, wyłączyć ani odebrać sobie roli właściciela.")
    if target["role"] == "owner" and (demote or deactivate or deleting):
        others = db.one("SELECT COUNT(*) n FROM users WHERE role='owner' AND active=1 AND id<>?", (target["id"],))["n"]
        if others < 1:
            errors.append("W programie musi pozostać co najmniej jeden aktywny właściciel.")
    return errors


@app.post("/panel/uzytkownicy/{uid}")
async def user_update(request: Request, uid: int):
    c = ctx(request)
    c.require_owner()
    before = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not before:
        raise HTTPException(404)
    form = await form_data(request)
    u, perms, errors = _parse_user_form(form, uid)
    if _primary_protected(c, before):
        # Login i e-mail głównego właściciela zmienia tylko on sam (w profilu albo tutaj na własnym koncie).
        u["username"], u["email"] = before["username"], before["email"]
        errors = [e for e in errors if "login" not in e.lower()]
    errors += _owner_guard(c, before, u["role"], u["active"])
    if errors:
        u["id"] = uid
        u["is_primary"] = before["is_primary"]
        return render(request, "panel/user_form.html", c, **_user_form_ctx(c, u, errors, perms),
                      protected=_primary_protected(c, before), session_count=sessions.count_user_sessions(uid))
    before_perms = _perm_summary(security.load_permissions(before)) if before["role"] == "user" else "właściciel – pełny dostęp"
    bump = 1 if (before["active"] and not u["active"]) or before["role"] != u["role"] else 0
    db.execute("""UPDATE users SET username=?, full_name=?, email=?, phone=?, role=?, employee_id=?, active=?,
                  notify_channel=?, session_version=session_version+? WHERE id=?""",
               (u["username"], u["full_name"], u["email"], u["phone"], u["role"], u["employee_id"], u["active"],
                u["notify_channel"], bump, uid))
    if bump:
        sessions.delete_user_sessions(uid)
    if before["role"] == "owner" and (u["role"] != "owner" or not u["active"]) and before["recovery_hash"]:
        # Wyłączenie konta lub odebranie roli właściciela unieważnia jego kod odzyskiwania.
        db.execute("UPDATE users SET recovery_hash=NULL, recovery_created_at=NULL WHERE id=?", (uid,))
    if u["role"] == "user":
        security.save_permissions(uid, perms)
    else:
        db.execute("DELETE FROM user_permissions WHERE user_id=?", (uid,))
    after = db.one("SELECT * FROM users WHERE id=?", (uid,))
    b, a = dict(before), dict(after)
    b["uprawnienia"] = before_perms
    a["uprawnienia"] = _perm_summary(perms) if u["role"] == "user" else "właściciel – pełny dostęp"
    c.audit("update", None, "konto", uid, f"Zmieniono konto {u['username']}", b, a)
    flash(request, "Zapisano konto i uprawnienia.")
    return go("/panel/uzytkownicy")


@app.post("/panel/uzytkownicy/{uid}/haslo")
async def user_reset_password(request: Request, uid: int):
    c = ctx(request)
    c.require_owner()
    await form_data(request)
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise HTTPException(404)
    if u["id"] == c.user["id"]:
        flash(request, "Własne hasło zmienisz w profilu.", "warn")
        return go(f"/panel/uzytkownicy/{uid}")
    if _primary_protected(c, u):
        flash(request, "Hasło głównego właściciela może zmienić tylko on sam (albo kodem odzyskiwania).", "error")
        return go(f"/panel/uzytkownicy/{uid}")
    pw = security.generate_temp_password()
    db.execute("""UPDATE users SET password_hash=?, must_change_password=1, failed_attempts=0, locked_until=NULL,
                  session_version=session_version+1 WHERE id=?""", (security.hash_password(pw), uid))
    sessions.delete_user_sessions(uid)
    c.audit("password_reset", None, "konto", uid, f"Nadano hasło tymczasowe dla {u['username']}")
    return render(request, "panel/temp_password.html", c, target=u, password=pw, created=False)


@app.post("/panel/uzytkownicy/{uid}/wyloguj")
async def user_logout_all(request: Request, uid: int):
    c = ctx(request)
    c.require_owner()
    await form_data(request)
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise HTTPException(404)
    if _primary_protected(c, u):
        flash(request, "Głównego właściciela może wylogować tylko on sam.", "error")
        return go(f"/panel/uzytkownicy/{uid}")
    n = sessions.count_user_sessions(uid)
    sessions.delete_user_sessions(uid, except_token_hash=request.scope.get("nz_session_hash"))
    if uid != c.user["id"]:
        db.execute("UPDATE users SET session_version=session_version+1 WHERE id=?", (uid,))
    c.audit("logout", None, "konto", uid, f"Właściciel wylogował konto {u['username']} na wszystkich urządzeniach")
    flash(request, f"Wylogowano konto {u['username']} (aktywnych sesji: {n}).")
    return go(f"/panel/uzytkownicy/{uid}")


@app.post("/panel/uzytkownicy/{uid}/odblokuj")
async def user_unlock(request: Request, uid: int):
    c = ctx(request)
    c.require_owner()
    await form_data(request)
    db.execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?", (uid,))
    c.audit("unlock", None, "konto", uid, "Odblokowano konto")
    flash(request, "Konto odblokowane.")
    return go(f"/panel/uzytkownicy/{uid}")


@app.post("/panel/uzytkownicy/{uid}/usun")
async def user_delete(request: Request, uid: int):
    c = ctx(request)
    c.require_owner()
    await form_data(request)
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise HTTPException(404)
    errors = _owner_guard(c, u, deleting=True)
    if errors:
        for e in errors:
            flash(request, e, "error")
        return go(f"/panel/uzytkownicy/{uid}")
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    c.audit("delete", None, "konto", uid, f"Usunięto konto {u['username']}", u, None)
    flash(request, f"Usunięto konto {u['username']}.")
    return go("/panel/uzytkownicy")


# ---------- Rodzaje spraw ----------

@app.get("/panel/rodzaje", response_class=HTMLResponse)
def categories_page(request: Request):
    c = ctx(request)
    c.require_owner()
    cats = svc.categories()
    usage = {(r["module"], r["category"]): r["n"] for r in db.query("SELECT module, category, COUNT(*) n FROM terms GROUP BY module, category")}
    for cat in cats:
        cat["used"] = usage.get((cat["module"], cat["name"]), 0)
    return render(request, "panel/categories.html", c, cats=cats)


@app.post("/panel/rodzaje")
async def categories_save(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    action = form.get("action")
    if action == "add":
        module = form.get("module")
        module_or_404(module)
        name = (form.get("name") or "").strip()
        iv = int_or_none(form.get("interval_value"))
        iu = form.get("interval_unit") if iv else None
        if not name:
            flash(request, "Podaj nazwę rodzaju sprawy.", "error")
        elif db.one("SELECT id FROM categories WHERE module=? AND name=? COLLATE NOCASE", (module, name)):
            flash(request, "Taki rodzaj już istnieje w tym module.", "error")
        else:
            cid = db.execute("INSERT INTO categories(module,name,interval_value,interval_unit,sort) VALUES(?,?,?,?,50)",
                             (module, name, iv, iu))
            c.audit("create", module, "rodzaj sprawy", cid, f"Dodano rodzaj sprawy: {name}")
            flash(request, f"Dodano: {name}.")
    elif action == "update":
        cid = int_or_none(form.get("id"))
        before = db.one("SELECT * FROM categories WHERE id=?", (cid,))
        if before:
            iv = int_or_none(form.get("interval_value"))
            iu = form.get("interval_unit") if iv else None
            db.execute("UPDATE categories SET interval_value=?, interval_unit=? WHERE id=?", (iv, iu, cid))
            c.audit("update", before["module"], "rodzaj sprawy", cid, f"Zmieniono cykl: {before['name']}", before,
                    db.one("SELECT * FROM categories WHERE id=?", (cid,)))
            flash(request, "Zapisano.")
    elif action == "delete":
        cid = int_or_none(form.get("id"))
        before = db.one("SELECT * FROM categories WHERE id=?", (cid,))
        if before:
            db.execute("DELETE FROM categories WHERE id=?", (cid,))
            c.audit("delete", before["module"], "rodzaj sprawy", cid, f"Usunięto rodzaj sprawy: {before['name']}", before, None)
            flash(request, f"Usunięto: {before['name']}. Istniejące terminy pozostały bez zmian.")
    return go("/panel/rodzaje")


# ---------- Własne pola ----------

@app.get("/panel/pola", response_class=HTMLResponse)
def fields_page(request: Request):
    c = ctx(request)
    c.require_owner()
    fields = db.query("SELECT * FROM custom_fields ORDER BY module, sort, name")
    return render(request, "panel/fields.html", c, fields=fields)


@app.post("/panel/pola")
async def fields_save(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    action = form.get("action")
    if action == "add":
        module = form.get("module")
        if module not in config.OBJECT_MODULES:
            raise HTTPException(400)
        name = (form.get("name") or "").strip()
        ftype = form.get("field_type") if form.get("field_type") in ("text", "number", "date") else "text"
        if not name:
            flash(request, "Podaj nazwę pola.", "error")
        elif db.one("SELECT id FROM custom_fields WHERE module=? AND name=? COLLATE NOCASE", (module, name)):
            flash(request, "Pole o tej nazwie już istnieje w tym module.", "error")
        else:
            fid = db.execute("INSERT INTO custom_fields(module,name,field_type,required) VALUES(?,?,?,?)",
                             (module, name, ftype, 1 if form.get("required") else 0))
            c.audit("create", module, "własne pole", fid, f"Dodano własne pole: {name}")
            flash(request, f"Dodano pole „{name}”.")
    elif action == "toggle":
        fid = int_or_none(form.get("id"))
        f = db.one("SELECT * FROM custom_fields WHERE id=?", (fid,))
        if f:
            db.execute("UPDATE custom_fields SET required=? WHERE id=?", (0 if f["required"] else 1, fid))
            c.audit("update", f["module"], "własne pole", fid, f"Zmieniono wymagalność pola: {f['name']}")
    elif action == "delete":
        fid = int_or_none(form.get("id"))
        f = db.one("SELECT * FROM custom_fields WHERE id=?", (fid,))
        if f:
            with db.tx() as conn:
                conn.execute("DELETE FROM custom_values WHERE field_id=?", (fid,))
                conn.execute("DELETE FROM custom_fields WHERE id=?", (fid,))
            c.audit("delete", f["module"], "własne pole", fid, f"Usunięto własne pole: {f['name']} (wraz z wartościami)", f, None)
            flash(request, f"Usunięto pole „{f['name']}”.")
    return go("/panel/pola")


# ---------- Ustawienia i szablony ----------

@app.get("/panel/ustawienia", response_class=HTMLResponse)
def settings_page(request: Request):
    c = ctx(request)
    c.require_owner()
    return render(request, "panel/settings.html", c, errors=[])


@app.post("/panel/ustawienia")
async def settings_save(request: Request):
    c = ctx(request)
    c.require_owner()
    form = await form_data(request)
    before = dict(c.settings)
    name = (form.get("company_name") or "").strip()
    remind = int_or_none(form.get("remind_days"))
    urgent = int_or_none(form.get("urgent_days"))
    errors = []
    if not name:
        errors.append("Podaj nazwę firmy.")
    if remind is None or not 1 <= remind <= 365:
        errors.append("Okres przypomnień: 1–365 dni.")
    if urgent is None or not 0 <= urgent <= (remind or 0):
        errors.append("Próg „pilne” musi być mniejszy lub równy okresowi przypomnień.")
    tpl = {k: (form.get(k) or "").strip() for k in ("template_sms", "template_email_subject", "template_email_body")}
    for k, v in tpl.items():
        if not v:
            tpl[k] = config.DEFAULT_SETTINGS[k]
    if errors:
        c.settings.update({"company_name": name, "remind_days": form.get("remind_days"), "urgent_days": form.get("urgent_days"), **tpl})
        return render(request, "panel/settings.html", c, errors=errors)
    for k, v in {"company_name": name, "remind_days": str(remind), "urgent_days": str(urgent), **tpl}.items():
        db.set_setting(k, v)
    c.audit("settings", None, "ustawienia", None, "Zmieniono ustawienia programu", before, db.get_settings())
    flash(request, "Zapisano ustawienia.")
    return go("/panel/ustawienia")


@app.post("/panel/ustawienia/domyslne-szablony")
async def templates_reset(request: Request):
    c = ctx(request)
    c.require_owner()
    await form_data(request)
    for k in ("template_sms", "template_email_subject", "template_email_body"):
        db.set_setting(k, config.DEFAULT_SETTINGS[k])
    c.audit("settings", None, "ustawienia", None, "Przywrócono domyślne szablony wiadomości")
    flash(request, "Przywrócono domyślne szablony.")
    return go("/panel/ustawienia")


# ---------- Kopie zapasowe ----------

@app.get("/panel/kopie", response_class=HTMLResponse)
def backups_page(request: Request):
    c = ctx(request)
    c.require_owner()
    return render(request, "panel/backups.html", c, backups=svc.list_backups(), backup_dir=str(config.BACKUP_DIR))


@app.post("/panel/kopie")
async def backup_create(request: Request):
    c = ctx(request)
    c.require_owner()
    await form_data(request)
    p = svc.create_backup("reczna")
    c.audit("backup", None, "kopia", None, f"Utworzono kopię zapasową {p.name}")
    flash(request, f"Utworzono kopię {p.name}.")
    return go("/panel/kopie")


@app.get("/panel/kopie/{name}")
def backup_download(request: Request, name: str):
    c = ctx(request)
    c.require_owner()
    p = config.BACKUP_DIR / Path(name).name
    if not p.exists() or not p.name.startswith("kopia-"):
        raise HTTPException(404)
    c.audit("backup_download", None, "kopia", None, f"Pobrano kopię {p.name}")
    return FileResponse(p, media_type="application/zip", filename=p.name)


# ---------- Dziennik zdarzeń ----------

AUDIT_ACTIONS = {
    "create": "Dodanie", "update": "Zmiana", "delete": "Usunięcie", "done": "Wykonanie", "reopen": "Cofnięcie wykonania",
    "notify": "Powiadomienie", "upload": "Dodanie pliku", "login": "Logowanie", "logout": "Wylogowanie",
    "login_failed": "Nieudane logowanie", "password": "Zmiana hasła", "password_reset": "Hasło tymczasowe",
    "recovery": "Odzyskanie konta", "recovery_code": "Nowy kod odzyskiwania", "unlock": "Odblokowanie konta",
    "export": "Eksport", "backup": "Kopia zapasowa", "backup_download": "Pobranie kopii", "settings": "Ustawienia",
    "setup": "Kreator", "notify_auto": "Powiadomienia automatyczne", "notify_test": "Test powiadomień",
    "import": "Import z Excela", "twofa": "Logowanie dwuetapowe", "update_check": "Aktualizacje", "remote": "Dostęp zdalny",
    "calendar": "Kalendarz",
}


def _audit_query(od="", do="", uzytkownik="", akcja="", modul="", q=""):
    sql, params = "SELECT * FROM audit_log WHERE 1=1", []
    if svc.parse_date(od):
        sql += " AND ts >= ?"
        params.append(od + " 00:00:00")
    if svc.parse_date(do):
        sql += " AND ts <= ?"
        params.append(do + " 23:59:59")
    if uzytkownik:
        sql += " AND username = ?"
        params.append(uzytkownik)
    if akcja:
        sql += " AND action = ?"
        params.append(akcja)
    if modul:
        sql += " AND module = ?"
        params.append(modul)
    if q:
        sql += " AND (description LIKE ? OR before_json LIKE ? OR after_json LIKE ?)"
        params += [f"%{q}%"] * 3
    return sql + " ORDER BY id DESC", params


@app.get("/panel/dziennik", response_class=HTMLResponse)
def audit_page(request: Request, od: str = "", do: str = "", uzytkownik: str = "", akcja: str = "",
               modul: str = "", q: str = "", strona: int = 1):
    c = ctx(request)
    c.require_owner()
    sql, params = _audit_query(od, do, uzytkownik, akcja, modul, q)
    per = 50
    strona = max(1, strona)
    total = db.one(f"SELECT COUNT(*) n FROM ({sql})", params)["n"]
    rows = db.query(sql + f" LIMIT {per} OFFSET {(strona - 1) * per}", params)
    for r in rows:
        r["changes"] = security.diff(r["before_json"], r["after_json"]) if r["action"] in ("update", "done", "reopen", "settings") else []
        r["snapshot"] = json.loads(r["after_json"] or r["before_json"] or "null") if r["action"] in ("create", "delete", "notify") else None
    users = [r["username"] for r in db.query("SELECT DISTINCT username FROM audit_log WHERE username IS NOT NULL ORDER BY username")]
    filters = dict(od=od, do=do, uzytkownik=uzytkownik, akcja=akcja, modul=modul, q=q)
    qs = "&".join(f"{k}={quote(str(v))}" for k, v in filters.items() if v)
    return render(request, "panel/audit.html", c, rows=rows, total=total, page=strona, pages=max(1, (total + per - 1) // per),
                  users=users, actions=AUDIT_ACTIONS, f=filters, qs=qs)


@app.get("/panel/dziennik.{fmt}")
def audit_export(request: Request, fmt: str, od: str = "", do: str = "", uzytkownik: str = "", akcja: str = "",
                 modul: str = "", q: str = ""):
    c = ctx(request)
    c.require_owner()
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(404)
    sql, params = _audit_query(od, do, uzytkownik, akcja, modul, q)
    rows = db.query(sql + " LIMIT 50000", params)
    headers = ["Data i godzina", "Użytkownik", "Operacja", "Moduł", "Rekord", "Opis", "Zmiany", "Adres IP"]
    out = []
    for r in rows:
        ch = security.diff(r["before_json"], r["after_json"])
        out.append([r["ts"], r["username"], AUDIT_ACTIONS.get(r["action"], r["action"]),
                    config.MODULES.get(r["module"], {}).get("label", ""),
                    f"{r['record_type'] or ''} #{r['record_id']}" if r["record_id"] else (r["record_type"] or ""),
                    r["description"], "; ".join(f"{k}: {b} → {a}" for k, b, a in ch) if r["action"] == "update" else "",
                    r["ip"]])
    c.audit("export", None, "dziennik", None, f"Eksport dziennika zdarzeń ({fmt}, {len(out)} wierszy)")
    return _export_response(fmt, "dziennik-zdarzen", "Dziennik", headers, out)


# Dodatkowe strony: pomoc, o programie, powiadomienia, dostęp zdalny, 2FA, import, kalendarz.
from . import extra  # noqa: E402,F401
