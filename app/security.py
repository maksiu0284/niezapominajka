"""Hasła, kody odzyskiwania, uprawnienia i dziennik zdarzeń."""
import hmac
import json
import math
import re
import secrets
import time

import bcrypt

from . import config, db

RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bez 0/O, 1/I


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode())
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = None


def burn_password_check(password: str):
    """Liczy bcrypt „na próżno”, żeby nieznany login odpowiadał tak samo długo jak znany."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    verify_password(password or "", _DUMMY_HASH)


# ---------- OGRANICZANIE PRÓB (wg adresu IP) ----------
# Konto nigdy się nie blokuje. Po LOGIN_FREE_FAILS nieudanych próbach z jednego adresu każda kolejna
# czeka coraz dłużej: 1, 2, 4, 8… sekund, maksymalnie LOGIN_MAX_DELAY sekund. Licznik zeruje się po
# udanym logowaniu z tego adresu albo po dobie bez błędów.

def throttle_wait(ip) -> int:
    """Ile sekund trzeba jeszcze odczekać (0 = można próbować)."""
    r = db.one("SELECT fails, last_fail, next_allowed FROM login_throttle WHERE ip=?", (ip or "?",))
    if not r:
        return 0
    now = time.time()
    if now - (r["last_fail"] or 0) > 86400:
        db.execute("DELETE FROM login_throttle WHERE ip=?", (ip or "?",))
        return 0
    return max(0, int(math.ceil((r["next_allowed"] or 0) - now)))


def throttle_fail(ip):
    ip = ip or "?"
    now = time.time()
    r = db.one("SELECT fails, last_fail FROM login_throttle WHERE ip=?", (ip,))
    fails = 1 if not r or now - (r["last_fail"] or 0) > 86400 else r["fails"] + 1
    delay = 0
    if fails >= config.LOGIN_FREE_FAILS:
        delay = min(2 ** (fails - config.LOGIN_FREE_FAILS), config.LOGIN_MAX_DELAY)
    db.execute("""INSERT INTO login_throttle(ip, fails, last_fail, next_allowed) VALUES(?,?,?,?)
                  ON CONFLICT(ip) DO UPDATE SET fails=excluded.fails, last_fail=excluded.last_fail,
                  next_allowed=excluded.next_allowed""", (ip, fails, now, now + delay))
    return delay


def throttle_reset(ip):
    db.execute("DELETE FROM login_throttle WHERE ip=?", (ip or "?",))


def wait_message(seconds: int) -> str:
    if seconds < 60:
        t = f"{seconds} s"
    else:
        t = f"{(seconds + 59) // 60} min"
    return f"Zbyt wiele nieudanych prób z tego urządzenia. Spróbuj ponownie za {t}."


def password_problems(password: str, username: str = "") -> list:
    """Zwraca listę niespełnionych wymagań silnego hasła."""
    problems = []
    if len(password) < 12:
        problems.append("co najmniej 12 znaków")
    if not re.search(r"[a-ząćęłńóśźż]", password):
        problems.append("mała litera")
    if not re.search(r"[A-ZĄĆĘŁŃÓŚŹŻ]", password):
        problems.append("wielka litera")
    if not re.search(r"\d", password):
        problems.append("cyfra")
    if not re.search(r"[^\w\s]|_", password):
        problems.append("znak specjalny, np. ! ? # %")
    if username and username.lower() in password.lower():
        problems.append("hasło nie może zawierać loginu")
    if len(set(password)) < 6:
        problems.append("zbyt mało różnych znaków")
    return problems


def generate_recovery_code() -> str:
    raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(20))
    return "-".join(raw[i:i + 5] for i in range(0, 20, 5))


def normalize_recovery_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def hash_recovery_code(code: str) -> str:
    return hash_password(normalize_recovery_code(code))


def verify_recovery_code(code: str, code_hash: str) -> bool:
    if not code_hash:
        return False
    return verify_password(normalize_recovery_code(code), code_hash)


def generate_temp_password() -> str:
    """Hasło tymczasowe nadawane przez właściciela – spełnia zasady siły."""
    while True:
        pw = (
            secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")
            + secrets.choice("abcdefghijkmnopqrstuvwxyz")
            + secrets.choice("23456789")
            + secrets.choice("!#%+=?")
            + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789")
                      for _ in range(10))
        )
        pw = "".join(secrets.SystemRandom().sample(pw, len(pw)))
        if not password_problems(pw):
            return pw


# ---------- CSRF ----------

def csrf_token(session) -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def csrf_valid(session, token) -> bool:
    expected = session.get("csrf")
    return bool(expected and token and hmac.compare_digest(expected, str(token)))


# ---------- UPRAWNIENIA ----------

def load_permissions(user) -> dict:
    """Słownik {moduł: {akcja: bool}}."""
    perms = {m: {a: False for a in config.ACTIONS} for m in config.MODULES}
    if not user:
        return perms
    if user["role"] == "owner":
        return {m: {a: True for a in config.ACTIONS} for m in config.MODULES}
    for r in db.query("SELECT * FROM user_permissions WHERE user_id=?", (user["id"],)):
        if r["module"] in perms:
            for a in config.ACTIONS:
                perms[r["module"]][a] = bool(r["can_" + a])
    # Brak podglądu = brak pozostałych uprawnień.
    for m in perms:
        if not perms[m]["view"]:
            perms[m] = {a: False for a in config.ACTIONS}
    return perms


def save_permissions(user_id, perms: dict):
    with db.tx() as c:
        c.execute("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
        for m, acts in perms.items():
            if not any(acts.values()):
                continue
            c.execute(
                """INSERT INTO user_permissions(user_id,module,can_view,can_add,can_edit,can_delete,can_notify)
                   VALUES(?,?,?,?,?,?,?)""",
                (user_id, m, *(int(bool(acts.get(a))) for a in config.ACTIONS)),
            )


# ---------- DZIENNIK ZDARZEŃ ----------

def _clean(d):
    if d is None:
        return None
    out = {}
    for k, v in dict(d).items():
        if k in ("password_hash", "recovery_hash", "session_version", "failed_attempts", "locked_until",
                 "totp_last"):
            continue
        if k in config.SECRET_SETTINGS or k in ("totp_secret", "calendar_token"):
            v = "•••" if v else ""
        if isinstance(v, bytes):
            v = "<plik>"
        out[k] = v
    return out


def audit(user, action, module=None, record_type=None, record_id=None,
          description="", before=None, after=None, ip=None):
    db.execute(
        """INSERT INTO audit_log(ts,user_id,username,action,module,record_type,record_id,
                                 description,before_json,after_json,ip)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            db.now_str(),
            user["id"] if user else None,
            user["username"] if user else None,
            action, module, record_type, record_id, description,
            json.dumps(_clean(before), ensure_ascii=False, default=str) if before is not None else None,
            json.dumps(_clean(after), ensure_ascii=False, default=str) if after is not None else None,
            ip,
        ),
    )


def diff(before_json, after_json):
    """Lista (pole, przed, po) dla zmienionych pól."""
    b = json.loads(before_json) if before_json else {}
    a = json.loads(after_json) if after_json else {}
    keys = [k for k in dict.fromkeys(list(b) + list(a)) if k not in ("updated_at", "created_at")]
    return [(k, b.get(k), a.get(k)) for k in keys if b.get(k) != a.get(k)]
