"""Niezapominajka – baza danych SQLite: schemat i proste funkcje pomocnicze."""
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    position TEXT,
    phone TEXT,
    email TEXT,
    contract_type TEXT,
    hired_on DATE,
    notes TEXT,
    photo_path TEXT,
    notify_channel TEXT NOT NULL DEFAULT 'none',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    registration TEXT NOT NULL UNIQUE,
    brand_model TEXT,
    vin TEXT,
    production_year INTEGER,
    responsible_employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    notes TEXT,
    photo_path TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS machines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    inventory_number TEXT UNIQUE,
    serial_number TEXT,
    manufacturer TEXT,
    location TEXT,
    responsible_employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    notes TEXT,
    photo_path TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    email TEXT,
    phone TEXT,
    role TEXT NOT NULL CHECK(role IN ('owner','user')),
    is_primary INTEGER NOT NULL DEFAULT 0,
    employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    active INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    session_version INTEGER NOT NULL DEFAULT 1,
    recovery_hash TEXT,
    recovery_created_at TEXT,
    last_login TEXT,
    totp_secret TEXT,
    totp_enabled INTEGER NOT NULL DEFAULT 0,
    totp_last INTEGER,
    calendar_token TEXT,
    notify_channel TEXT NOT NULL DEFAULT 'none',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module TEXT NOT NULL,
    can_view INTEGER NOT NULL DEFAULT 0,
    can_add INTEGER NOT NULL DEFAULT 0,
    can_edit INTEGER NOT NULL DEFAULT 0,
    can_delete INTEGER NOT NULL DEFAULT 0,
    can_notify INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, module)
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,
    name TEXT NOT NULL,
    interval_value INTEGER,
    interval_unit TEXT,
    sort INTEGER NOT NULL DEFAULT 0,
    UNIQUE(module, name)
);

CREATE TABLE IF NOT EXISTS terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,
    object_id INTEGER,
    category TEXT NOT NULL,
    title TEXT,
    due_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','done')),
    done_date DATE,
    done_note TEXT,
    done_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    interval_value INTEGER,
    interval_unit TEXT,
    remind_days INTEGER,
    responsible_employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    counterparty TEXT,
    amount REAL,
    document_number TEXT,
    notes TEXT,
    previous_id INTEGER REFERENCES terms(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_terms_due ON terms(status, due_date);
CREATE INDEX IF NOT EXISTS idx_terms_obj ON terms(module, object_id);

CREATE TABLE IF NOT EXISTS custom_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,
    name TEXT NOT NULL,
    field_type TEXT NOT NULL CHECK(field_type IN ('text','number','date')),
    required INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    UNIQUE(module, name)
);

CREATE TABLE IF NOT EXISTS custom_values (
    module TEXT NOT NULL,
    object_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL REFERENCES custom_fields(id) ON DELETE CASCADE,
    value TEXT,
    PRIMARY KEY(module, object_id, field_id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,
    object_id INTEGER,
    term_id INTEGER REFERENCES terms(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    mime TEXT,
    size INTEGER,
    uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    uploaded_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    module TEXT,
    record_type TEXT,
    record_id INTEGER,
    description TEXT,
    before_json TEXT,
    after_json TEXT,
    ip TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

-- Automatyczne powiadomienia: co, komu i kiedy wysłano (żeby nie wysyłać dwa razy).
CREATE TABLE IF NOT EXISTS notification_sent (
    term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
    recipient TEXT NOT NULL,
    channel TEXT NOT NULL,
    stage TEXT NOT NULL,
    ts TEXT NOT NULL,
    PRIMARY KEY(term_id, recipient, channel, stage)
);

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    channel TEXT NOT NULL,
    recipient TEXT,
    address TEXT,
    term_id INTEGER,
    subject TEXT,
    ok INTEGER NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_notif_ts ON notification_log(ts);

-- Sesje po stronie serwera (od 1.0.2). id = skrót SHA-256 identyfikatora z ciasteczka.
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER,
    data TEXT,
    created_at TEXT,
    last_seen TEXT,
    expires_at REAL NOT NULL,
    ip TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- Nieudane logowania wg adresu IP (od 1.0.2) – zamiast blokowania kont.
CREATE TABLE IF NOT EXISTS login_throttle (
    ip TEXT PRIMARY KEY,
    fails INTEGER NOT NULL DEFAULT 0,
    last_fail REAL,
    next_allowed REAL
);
"""


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql, params=()):
    with tx() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def one(sql, params=()):
    with tx() as c:
        r = c.execute(sql, params).fetchone()
        return dict(r) if r else None


def execute(sql, params=()):
    with tx() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def _restrict_data_dir():
    """Linux/AppImage: folder danych niedostępny dla innych kont systemu (bez praw dla „others”)."""
    if os.name != "posix":
        return
    try:
        mode = config.DATA_DIR.stat().st_mode & 0o777
        if mode & 0o007:
            os.chmod(config.DATA_DIR, mode & ~0o007)
    except OSError:
        pass


def init():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _restrict_data_dir()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    config.TMP_DIR.mkdir(parents=True, exist_ok=True)
    with tx() as c:
        c.executescript(SCHEMA)
        for k, v in config.DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        if not c.execute("SELECT 1 FROM categories LIMIT 1").fetchone():
            for i, (m, n, iv, iu) in enumerate(config.DEFAULT_CATEGORIES):
                c.execute(
                    "INSERT INTO categories(module,name,interval_value,interval_unit,sort) VALUES(?,?,?,?,?)",
                    (m, n, iv, iu, i),
                )
        # 1.0.2: konta nie są już blokowane po błędnych hasłach – zdejmujemy stare blokady.
        c.execute("UPDATE users SET locked_until=NULL, failed_attempts=0 WHERE locked_until IS NOT NULL OR failed_attempts<>0")
    # 1.0.2: klucz podpisu ciasteczek nie jest już potrzebny (sesje są na serwerze).
    try:
        (config.DATA_DIR / "klucz_sesji.txt").unlink(missing_ok=True)
    except OSError:
        pass
    # 1.0.2: typ załączników ustalany po zawartości – poprawiamy rekordy zapisane wcześniej.
    from . import files
    files.fix_stored_types(sys.modules[__name__], config.UPLOAD_DIR)


def get_settings():
    return {r["key"]: r["value"] for r in query("SELECT key, value FROM settings")}


def set_setting(key, value):
    execute(
        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
