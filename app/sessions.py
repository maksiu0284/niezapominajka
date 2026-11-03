"""Sesje przechowywane na serwerze (w bazie), a nie w ciasteczku.

Ciasteczko zawiera tylko losowy identyfikator. W bazie zapisujemy jego skrót SHA-256,
więc nawet odczyt pliku bazy nie daje działającej sesji. Wylogowanie usuwa sesję od razu.
"""
import hashlib
import json
import secrets
import time
from http.cookies import SimpleCookie
from urllib.parse import urlparse

from . import config, db

COOKIE = "niezapominajka_sid"
OLD_COOKIES = ("niezapominajka_sesja",)  # ciasteczko podpisane z wersji 1.0.0–1.0.1


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now():
    return time.time()


def _load(token):
    if not token or len(token) > 100:
        return None
    row = db.one("SELECT data, expires_at FROM sessions WHERE id=?", (_hash(token),))
    if not row or row["expires_at"] < _now():
        return None
    try:
        return json.loads(row["data"] or "{}")
    except ValueError:
        return {}


def _save(token, data, scope):
    headers = dict(scope.get("headers") or [])
    ua = headers.get(b"user-agent", b"").decode("latin-1")[:200]
    ip = (scope.get("client") or ("", 0))[0]
    exp = _now() + config.SESSION_HOURS * 3600
    db.execute(
        """INSERT INTO sessions(id, user_id, data, created_at, last_seen, expires_at, ip, user_agent)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET user_id=excluded.user_id, data=excluded.data,
                last_seen=excluded.last_seen, expires_at=excluded.expires_at, ip=excluded.ip,
                user_agent=excluded.user_agent""",
        (_hash(token), data.get("uid"), json.dumps(data, ensure_ascii=False, default=str),
         db.now_str(), db.now_str(), exp, ip, ua),
    )


def _delete(token):
    if token:
        db.execute("DELETE FROM sessions WHERE id=?", (_hash(token),))


def delete_user_sessions(user_id, except_token_hash=None):
    """Wylogowuje użytkownika na wszystkich urządzeniach."""
    if except_token_hash:
        db.execute("DELETE FROM sessions WHERE user_id=? AND id<>?", (user_id, except_token_hash))
    else:
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def count_user_sessions(user_id):
    return db.one("SELECT COUNT(*) n FROM sessions WHERE user_id=? AND expires_at>?", (user_id, _now()))["n"]


def purge_expired():
    db.execute("DELETE FROM sessions WHERE expires_at<?", (_now(),))


def is_https(scope) -> bool:
    """Czy przeglądarka łączy się przez HTTPS – bezpośrednio albo przez Tailscale/Cloudflare/proxy.

    Uvicorn ustawia scheme=https na podstawie X-Forwarded-Proto tylko dla połączeń z 127.0.0.1
    (pośrednik na tym samym komputerze). Dodatkowo rozpoznajemy adres publiczny z panelu.
    """
    if scope.get("scheme") in ("https", "wss"):
        return True
    headers = dict(scope.get("headers") or [])
    client = (scope.get("client") or ("", 0))[0]
    if client in ("127.0.0.1", "::1"):
        if headers.get(b"x-forwarded-proto", b"").decode("latin-1").lower() == "https":
            return True
        try:
            public = db.get_settings().get("public_url") or ""
        except Exception:
            public = ""
        if public.startswith("https://"):
            host = headers.get(b"host", b"").decode("latin-1").split(":")[0].lower()
            if host and host == (urlparse(public).hostname or "").lower():
                return True
    return False


class ServerSessionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path.startswith("/static/") or path in ("/sw.js", "/manifest.webmanifest"):
            scope["session"] = {}
            await self.app(scope, receive, send)
            return
        cookie = SimpleCookie()
        raw = dict(scope.get("headers") or []).get(b"cookie", b"").decode("latin-1")
        try:
            cookie.load(raw)
        except Exception:
            pass
        token = cookie[COOKIE].value if COOKIE in cookie else None
        data = _load(token)
        had_old = any(k in cookie for k in OLD_COOKIES)
        if data is None:
            token, data = None, {}
        original = json.dumps(data, sort_keys=True, default=str)
        scope["session"] = data
        scope["nz_session_hash"] = _hash(token) if token else None
        secure = is_https(scope)

        async def send_wrapper(message):
            nonlocal token
            if message["type"] == "http.response.start":
                sess = scope["session"]
                rotate = scope.get("nz_rotate")
                destroy = scope.get("nz_destroy")
                changed = json.dumps(sess, sort_keys=True, default=str) != original
                cookies = []
                if destroy:
                    _delete(token)
                    token = None
                    if sess:  # po wylogowaniu zostaje np. komunikat – nowa, pusta sesja
                        token = secrets.token_urlsafe(32)
                        _save(token, sess, scope)
                elif rotate and sess:
                    _delete(token)
                    token = secrets.token_urlsafe(32)
                    _save(token, sess, scope)
                elif changed:
                    if sess:
                        if not token:
                            token = secrets.token_urlsafe(32)
                        _save(token, sess, scope)
                    else:
                        _delete(token)
                        token = None
                attrs = "Path=/; HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")
                if token and (changed or rotate or destroy):
                    cookies.append(f"{COOKIE}={token}; Max-Age={config.SESSION_HOURS * 3600}; {attrs}")
                elif not token and (changed or destroy) and COOKIE in cookie:
                    cookies.append(f"{COOKIE}=; Max-Age=0; {attrs}")
                if had_old:
                    for name in OLD_COOKIES:
                        cookies.append(f"{name}=; Max-Age=0; Path=/")
                if cookies:
                    hdrs = list(message.get("headers") or [])
                    for c in cookies:
                        hdrs.append((b"set-cookie", c.encode("latin-1")))
                    message["headers"] = hdrs
            await send(message)

        await self.app(scope, receive, send_wrapper)


def rotate(request):
    """Nowy identyfikator sesji po zalogowaniu (ochrona przed podstawieniem sesji)."""
    request.scope["nz_rotate"] = True


def destroy(request):
    """Usuwa bieżącą sesję z serwera (wylogowanie)."""
    request.scope["nz_destroy"] = True
