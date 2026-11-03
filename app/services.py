"""Logika terminów, obiektów, eksportu i kopii zapasowych."""
import calendar
import csv
import io
import shutil
import sqlite3
import zipfile
from datetime import date, datetime, timedelta

from . import config, db

PL_MONTHS = ["", "sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


# ---------- DATY ----------

def parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_date(value):
    d = parse_date(value)
    return d.strftime("%d.%m.%Y") if d else "—"


def add_interval(d: date, value: int, unit: str) -> date:
    if not d or not value or not unit:
        return None
    if unit == "days":
        return d + timedelta(days=value)
    months = value if unit == "months" else value * 12
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def days_word(n):
    n = abs(n)
    if n == 1:
        return "1 dzień"
    return f"{n} dni"


def left_label(days):
    if days is None:
        return "—"
    if days == 0:
        return "dziś"
    if days == 1:
        return "jutro"
    if days < 0:
        return f"{days_word(days)} po terminie"
    return f"za {days_word(days)}"


# ---------- OBIEKTY ----------

def object_display(module, row):
    if not row:
        return "—"
    if module == "employees":
        return f"{row['first_name']} {row['last_name']}"
    if module == "vehicles":
        return f"{row['name']} ({row['registration']})"
    if module == "machines":
        inv = f" ({row['inventory_number']})" if row.get("inventory_number") else ""
        return f"{row['name']}{inv}"
    return "Firma"


def object_order(module):
    return "last_name, first_name" if module == "employees" else "name"


def get_object(module, object_id):
    meta = config.MODULES.get(module)
    if not meta or not meta["has_objects"]:
        return None
    return db.one(f"SELECT * FROM {meta['table']} WHERE id=?", (object_id,))


def all_objects(module):
    meta = config.MODULES[module]
    return db.query(f"SELECT * FROM {meta['table']} ORDER BY {object_order(module)}")


def employees_brief():
    return db.query(
        "SELECT id, first_name, last_name, phone, email, position FROM employees ORDER BY last_name, first_name"
    )


def name_maps():
    maps = {}
    for m in config.OBJECT_MODULES:
        maps[m] = {r["id"]: r for r in all_objects(m)}
    return maps


# ---------- TERMINY ----------

def term_status(term, settings):
    if term["status"] == "done":
        return "done"
    d = parse_date(term["due_date"])
    left = (d - date.today()).days
    urgent = int(settings.get("urgent_days") or 7)
    remind = term.get("remind_days")
    remind = int(remind) if remind not in (None, "") else int(settings.get("remind_days") or 30)
    if left < 0:
        return "overdue"
    if left <= urgent:
        return "urgent"
    if left <= remind:
        return "soon"
    return "ok"


STATUS_LABELS = {
    "overdue": "Po terminie",
    "urgent": "Pilne",
    "soon": "Wkrótce",
    "ok": "W normie",
    "done": "Wykonane",
}


def enrich_terms(terms, settings, maps=None):
    maps = maps or name_maps()
    emps = maps["employees"]
    out = []
    for t in terms:
        t = dict(t)
        d = parse_date(t["due_date"])
        t["days_left"] = (d - date.today()).days if d else None
        t["status_key"] = term_status(t, settings)
        t["status_label"] = STATUS_LABELS[t["status_key"]]
        t["left_label"] = left_label(t["days_left"]) if t["status"] == "open" else "wykonane " + fmt_date(t["done_date"])
        if t["module"] in config.OBJECT_MODULES:
            obj = maps[t["module"]].get(t["object_id"])
            t["object_name"] = object_display(t["module"], obj) if obj else "(usunięty)"
        else:
            t["object_name"] = t.get("counterparty") or "Firma"
        resp = emps.get(t.get("responsible_employee_id"))
        t["responsible"] = resp
        t["responsible_name"] = f"{resp['first_name']} {resp['last_name']}" if resp else ""
        t["display_title"] = t["category"] + (f" – {t['title']}" if t.get("title") else "")
        t["recurring"] = bool(t.get("interval_value") and t.get("interval_unit"))
        out.append(t)
    return out


def own_employee_filter(user):
    """Warunek SQL dla terminów powiązanych z pracownikiem użytkownika."""
    if user and user.get("employee_id"):
        eid = int(user["employee_id"])
        return (
            "((module='employees' AND object_id=?) OR responsible_employee_id=?)",
            [eid, eid],
        )
    return None, []


def visible_terms_sql(user, perms):
    """Zwraca (warunek, parametry) dla terminów widocznych dla użytkownika."""
    mods = [m for m in config.MODULES if perms[m]["view"]]
    parts, params = [], []
    if mods:
        parts.append("module IN (%s)" % ",".join("?" * len(mods)))
        params += mods
    own, own_p = own_employee_filter(user)
    if own:
        parts.append(own)
        params += own_p
    if not parts:
        return "0", []
    return "(" + " OR ".join(parts) + ")", params


def can_see_term(user, perms, term):
    if perms[term["module"]]["view"]:
        return True
    eid = user.get("employee_id")
    if eid and (
        (term["module"] == "employees" and term["object_id"] == eid)
        or term.get("responsible_employee_id") == eid
    ):
        return True
    return False


def default_responsible(module, object_id):
    if module == "employees":
        return object_id
    if module in ("vehicles", "machines") and object_id:
        obj = get_object(module, object_id)
        return obj.get("responsible_employee_id") if obj else None
    return None


def categories(module=None):
    if module:
        return db.query("SELECT * FROM categories WHERE module=? ORDER BY sort, name", (module,))
    return db.query("SELECT * FROM categories ORDER BY module, sort, name")


# ---------- WŁASNE POLA ----------

def custom_fields(module):
    return db.query("SELECT * FROM custom_fields WHERE module=? ORDER BY sort, name", (module,))


def custom_values(module, object_id):
    rows = db.query(
        "SELECT field_id, value FROM custom_values WHERE module=? AND object_id=?", (module, object_id)
    )
    return {r["field_id"]: r["value"] for r in rows}


def save_custom_values(conn, module, object_id, values: dict):
    for fid, val in values.items():
        conn.execute(
            """INSERT INTO custom_values(module,object_id,field_id,value) VALUES(?,?,?,?)
               ON CONFLICT(module,object_id,field_id) DO UPDATE SET value=excluded.value""",
            (module, object_id, fid, val),
        )


# ---------- POWIADOMIENIA ----------

def render_template(tpl, term, settings, sender, recipient_name):
    data = {
        "osoba": recipient_name or "",
        "firma": settings.get("company_name") or "",
        "sprawa": term["display_title"],
        "obiekt": term["object_name"],
        "termin": fmt_date(term["due_date"]),
        "ile": term["left_label"],
        "nadawca": (sender.get("full_name") or sender.get("username")) if sender else "",
    }
    out = tpl or ""
    for k, v in data.items():
        out = out.replace("{" + k + "}", str(v))
    return out.strip()


def normalize_phone(phone):
    if not phone:
        return ""
    p = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if p.startswith("00"):
        p = "+" + p[2:]
    if not p.startswith("+") and len(p) == 9:
        p = "+48" + p
    return p


# ---------- EKSPORT ----------

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(v):
    """Tekst zaczynający się od =, +, -, @, tab lub CR Excel potraktowałby jak formułę –
    poprzedzamy go apostrofem. Liczby zostają liczbami."""
    if v is None:
        return ""
    if isinstance(v, str) and v.startswith(_FORMULA_START):
        return "'" + v
    return v


def to_csv(headers, rows):
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM – poprawne polskie znaki w Excelu
    w = csv.writer(buf, delimiter=";")
    w.writerow([csv_safe(h) for h in headers])
    for r in rows:
        w.writerow([csv_safe(v) for v in r])
    return buf.getvalue().encode("utf-8")


def to_xlsx(title, headers, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2F4A55")
    for r in rows:
        ws.append(["" if v is None else v for v in r])
    # Teksty zapisujemy zawsze jako tekst – nawet "=..." nie stanie się formułą.
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith(_FORMULA_START):
                cell.data_type = "s"
    for i, h in enumerate(headers, 1):
        width = max([len(str(h))] + [len(str(r[i - 1] or "")) for r in rows[:500]]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(width, 60)
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- KOPIE ZAPASOWE ----------

def create_backup(label="auto"):
    """Tworzy plik ZIP z bazą (spójna kopia SQLite) i załącznikami."""
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = config.BACKUP_DIR / f"kopia-{stamp}-{label}.zip"
    tmp_db = config.BACKUP_DIR / f".tmp-{stamp}.db"
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(tmp_db)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_db, config.DB_NAME)
        for f in config.UPLOAD_DIR.glob("*"):
            if f.is_file():
                z.write(f, f"zalaczniki/{f.name}")
    tmp_db.unlink(missing_ok=True)
    prune_backups()
    return zip_path


def prune_backups():
    autos = sorted(config.BACKUP_DIR.glob("kopia-*-auto.zip"))
    for f in autos[:-config.BACKUP_KEEP]:
        f.unlink(missing_ok=True)


def list_backups():
    files = sorted(config.BACKUP_DIR.glob("kopia-*.zip"), reverse=True)
    return [
        {"name": f.name, "size": f.stat().st_size,
         "time": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M")}
        for f in files
    ]


def last_auto_backup_age_hours():
    autos = sorted(config.BACKUP_DIR.glob("kopia-*-auto.zip"))
    if not autos:
        return None
    return (datetime.now().timestamp() - autos[-1].stat().st_mtime) / 3600


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def safe_copy(src, dst):
    shutil.copyfile(src, dst)


# ---------- SIEĆ ----------

def lan_address():
    """Adres IP komputera w sieci lokalnej (do linków i adresu dla telefonu)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "localhost"


# ---------- AKTUALIZACJE ----------

def _version_tuple(v):
    out = []
    for part in str(v).lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


def check_updates():
    """Sprawdza najnowsze wydanie na GitHub. Zwraca (wersja, adres) albo zgłasza wyjątek."""
    import json
    import urllib.request
    req = urllib.request.Request(config.RELEASES_API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code == 404:
            data = {}
        elif code in (403, 429):
            raise RuntimeError("GitHub chwilowo ogranicza liczbę zapytań z tej sieci. Spróbuj ponownie za godzinę.")
        else:
            raise RuntimeError(f"Nie udało się połączyć z GitHub: {getattr(exc, 'reason', exc)}")
    latest = (data.get("tag_name") or "").lstrip("vV")
    url = data.get("html_url") or config.RELEASES_URL
    db.set_setting("update_latest", latest)
    db.set_setting("update_url", url)
    db.set_setting("update_checked_at", db.now_str())
    return latest, url


def update_available(settings):
    latest = settings.get("update_latest")
    return bool(latest) and _version_tuple(latest) > _version_tuple(config.APP_VERSION)


# ---------- KALENDARZ (iCalendar .ics) ----------

def _ics_escape(text):
    return (str(text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _ics_fold(line):
    raw = line.encode("utf-8")
    if len(raw) <= 74:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 73:
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def terms_to_ics(terms, settings, base_url=""):
    company = settings.get("company_name") or config.APP_NAME
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{config.APP_NAME}//{config.APP_VERSION}//PL",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_escape(config.APP_NAME + ' – ' + company)}",
             "X-WR-TIMEZONE:Europe/Warsaw"]
    for t in terms:
        d = parse_date(t["due_date"])
        if not d:
            continue
        remind = t.get("remind_days")
        remind = int(remind) if remind not in (None, "") else int(settings.get("remind_days") or 30)
        desc = [f"Dotyczy: {t['object_name']}"]
        if t.get("responsible_name"):
            desc.append(f"Odpowiada: {t['responsible_name']}")
        if t.get("notes"):
            desc.append(f"Uwagi: {t['notes']}")
        if base_url:
            desc.append(f"{base_url}/terminy/{t['id']}")
        lines += [
            "BEGIN:VEVENT",
            f"UID:termin-{t['id']}@niezapominajka",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_ics_escape(t['display_title'] + ' – ' + t['object_name'])}",
            f"DESCRIPTION:{_ics_escape(chr(10).join(desc))}",
            f"CATEGORIES:{_ics_escape(config.MODULES[t['module']]['label'])}",
            "TRANSP:TRANSPARENT",
        ]
        if base_url:
            lines.append(f"URL:{base_url}/terminy/{t['id']}")
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(t['display_title'])}",
                  f"TRIGGER:-P{max(int(settings.get('urgent_days') or 7), 1)}D", "END:VALARM"]
        if remind:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(t['display_title'])}",
                      f"TRIGGER:-P{remind}D", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(x) for x in lines) + "\r\n"
