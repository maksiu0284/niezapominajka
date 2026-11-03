"""Konfiguracja programu Niezapominajka."""
import os
import sys
from pathlib import Path

APP_NAME = "Niezapominajka"
APP_VERSION = "1.0.2"
APP_TAGLINE = "Przypominajka ważnych terminów w firmie"
AUTHOR = "Maksymilian Staszewski"
AUTHOR_EMAIL = "maksymilianstaszewski@gmail.com"
HOMEPAGE = "https://github.com/maksiu0284/niezapominajka"
SPONSOR_URL = "https://github.com/sponsors/maksiu0284"
RELEASES_API = "https://api.github.com/repos/maksiu0284/niezapominajka/releases/latest"
RELEASES_URL = HOMEPAGE + "/releases"
LICENSE_NAME = "GNU Affero General Public License v3.0 (AGPL-3.0)"

FROZEN = bool(getattr(sys, "frozen", False))
# Katalog z kodem programu (szablony, pliki statyczne). W wersji exe – katalog rozpakowania.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "app" if FROZEN \
    else Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent


def _default_data_dir() -> Path:
    """Gdzie trzymać dane, jeśli nie podano NIEZAPOMINAJKA_DANE.

    - AppImage (Linux): ~/.local/share/niezapominajka (obraz jest tylko do odczytu),
    - exe zainstalowany w Program Files: %ProgramData%\\Niezapominajka,
    - exe przenośny: folder „dane” obok pliku exe,
    - uruchomienie ze źródeł: folder „dane” obok run.py.
    """
    if os.environ.get("APPIMAGE"):
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return Path(base) / "niezapominajka"
    if FROZEN:
        exe_dir = Path(sys.executable).resolve().parent
        if os.name == "nt" and "program files" in str(exe_dir).lower():
            return Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Niezapominajka"
        return exe_dir / "dane"
    return ROOT_DIR / "dane"


DATA_DIR = Path(os.environ.get("NIEZAPOMINAJKA_DANE") or _default_data_dir()).expanduser().resolve()
DB_NAME = "niezapominajka.db"
DB_PATH = DATA_DIR / DB_NAME
UPLOAD_DIR = DATA_DIR / "zalaczniki"
BACKUP_DIR = DATA_DIR / "kopie"
TMP_DIR = DATA_DIR / "tymczasowe"
LOG_FILE = DATA_DIR / "niezapominajka.log"

HOST = os.environ.get("NIEZAPOMINAJKA_HOST", "0.0.0.0")
PORT = int(os.environ.get("NIEZAPOMINAJKA_PORT", "8000"))

MAX_UPLOAD_MB = 25
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ods", ".odt", ".odp",
    ".ppt", ".pptx", ".txt", ".rtf", ".csv",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
# Wersja przenośna (exe): dane w folderze „dane” obok pliku programu.
PORTABLE = FROZEN and os.name == "nt" and "program files" not in str(Path(sys.executable).resolve().parent).lower()

LOGIN_FREE_FAILS = 5        # tyle błędów z jednego adresu bez opóźnienia
LOGIN_MAX_DELAY = 15 * 60   # najdłuższe opóźnienie kolejnej próby (sekundy)
SESSION_HOURS = 12
BACKUP_KEEP = 14

USER_CHANNELS = {
    "none": "Bez automatycznych powiadomień",
    "email": "E-mail",
    "sms": "SMS",
    "both": "E-mail i SMS",
}

# Moduły programu. Klucz = identyfikator w bazie.
MODULES = {
    "employees": {
        "label": "Pracownicy",
        "single": "Pracownik",
        "new": "Nowy pracownik",
        "icon": "users",
        "color": "sage",
        "table": "employees",
        "has_objects": True,
        "fields": [
            {"name": "first_name", "label": "Imię", "type": "text", "required": True},
            {"name": "last_name", "label": "Nazwisko", "type": "text", "required": True},
            {"name": "position", "label": "Stanowisko", "type": "text"},
            {"name": "phone", "label": "Telefon (do SMS)", "type": "tel"},
            {"name": "email", "label": "E-mail", "type": "email"},
            {"name": "contract_type", "label": "Rodzaj umowy", "type": "text"},
            {"name": "hired_on", "label": "Data zatrudnienia", "type": "date"},
            {"name": "notify_channel", "label": "Automatyczne powiadomienia", "type": "select",
             "options": USER_CHANNELS, "default": "none",
             "hint": "Działa, gdy właściciel włączy automatyczne powiadomienia w panelu."},
            {"name": "notes", "label": "Uwagi", "type": "textarea"},
        ],
        "list_fields": ["position", "phone"],
    },
    "vehicles": {
        "label": "Pojazdy",
        "single": "Pojazd",
        "new": "Nowy pojazd",
        "icon": "truck",
        "color": "blue",
        "table": "vehicles",
        "has_objects": True,
        "fields": [
            {"name": "name", "label": "Nazwa / oznaczenie", "type": "text", "required": True},
            {"name": "registration", "label": "Numer rejestracyjny", "type": "text",
             "required": True, "unique": True, "upper": True},
            {"name": "brand_model", "label": "Marka i model", "type": "text"},
            {"name": "vin", "label": "VIN", "type": "text", "upper": True},
            {"name": "production_year", "label": "Rok produkcji", "type": "number"},
            {"name": "responsible_employee_id", "label": "Kierowca / opiekun", "type": "employee"},
            {"name": "notes", "label": "Uwagi", "type": "textarea"},
        ],
        "list_fields": ["registration", "brand_model"],
    },
    "machines": {
        "label": "Maszyny",
        "single": "Maszyna",
        "new": "Nowa maszyna",
        "icon": "cog",
        "color": "amber",
        "table": "machines",
        "has_objects": True,
        "fields": [
            {"name": "name", "label": "Nazwa maszyny", "type": "text", "required": True},
            {"name": "inventory_number", "label": "Numer inwentarzowy", "type": "text",
             "unique": True, "upper": True},
            {"name": "serial_number", "label": "Numer seryjny", "type": "text"},
            {"name": "manufacturer", "label": "Producent / model", "type": "text"},
            {"name": "location", "label": "Lokalizacja / hala", "type": "text"},
            {"name": "responsible_employee_id", "label": "Opiekun maszyny", "type": "employee"},
            {"name": "notes", "label": "Uwagi", "type": "textarea"},
        ],
        "list_fields": ["inventory_number", "location"],
    },
    "company": {
        "label": "Sprawy firmy",
        "single": "Sprawa firmy",
        "new": "Nowy termin firmy",
        "icon": "briefcase",
        "color": "plum",
        "table": None,
        "has_objects": False,
        "fields": [],
        "list_fields": [],
    },
}
OBJECT_MODULES = [k for k, v in MODULES.items() if v["has_objects"]]

ACTIONS = {
    "view": "Podgląd",
    "add": "Dodawanie",
    "edit": "Edycja",
    "delete": "Usuwanie",
    "notify": "Powiadamianie",
}

INTERVAL_UNITS = {"days": "dni", "months": "miesięcy", "years": "lat"}

# (moduł, nazwa, co ile, jednostka)
DEFAULT_CATEGORIES = [
    ("employees", "Badania lekarskie okresowe", None, None),
    ("employees", "Szkolenie BHP okresowe", None, None),
    ("employees", "Koniec umowy", None, None),
    ("employees", "Uprawnienia (UDT, SEP, prawo jazdy)", None, None),
    ("employees", "Badania psychotechniczne", 5, "years"),
    ("employees", "Ubezpieczenie pracownika", 12, "months"),
    ("employees", "Inne", None, None),
    ("vehicles", "Przegląd techniczny", 12, "months"),
    ("vehicles", "Ubezpieczenie OC", 12, "months"),
    ("vehicles", "Ubezpieczenie AC", 12, "months"),
    ("vehicles", "Serwis okresowy", 12, "months"),
    ("vehicles", "Wymiana opon", 6, "months"),
    ("vehicles", "Legalizacja tachografu", 2, "years"),
    ("vehicles", "Rata leasingu", 1, "months"),
    ("vehicles", "Inne", None, None),
    ("machines", "Przegląd okresowy", 12, "months"),
    ("machines", "Serwis", 6, "months"),
    ("machines", "Badanie UDT", 12, "months"),
    ("machines", "Pomiary elektryczne", 5, "years"),
    ("machines", "Kalibracja / legalizacja", 12, "months"),
    ("machines", "Inne", None, None),
    ("company", "Płatność", 1, "months"),
    ("company", "Podatek", 1, "months"),
    ("company", "ZUS", 1, "months"),
    ("company", "Licencja / abonament", 12, "months"),
    ("company", "Umowa najmu / dzierżawy", None, None),
    ("company", "Ubezpieczenie firmy", 12, "months"),
    ("company", "Inne", None, None),
]

DEFAULT_TEMPLATES = {
    "sms": "Dzień dobry {osoba}. Przypomnienie z firmy {firma}: {sprawa} – {obiekt}. Termin: {termin} ({ile}). Proszę o zajęcie się sprawą.",
    "email_subject": "Przypomnienie: {sprawa} – termin {termin}",
    "email_body": "Dzień dobry {osoba},\n\nprzypominam o terminie: {sprawa}\nDotyczy: {obiekt}\nTermin: {termin} ({ile})\n\nProszę o zajęcie się sprawą.\n\nPozdrawiam\n{nadawca}\n{firma}",
}

DEFAULT_SETTINGS = {
    "company_name": "",
    "remind_days": "30",
    "urgent_days": "7",
    "setup_done": "0",
    "template_sms": DEFAULT_TEMPLATES["sms"],
    "template_email_subject": DEFAULT_TEMPLATES["email_subject"],
    "template_email_body": DEFAULT_TEMPLATES["email_body"],
    # Sprawdzanie aktualizacji (dobrowolne)
    "update_check": "0",
    "update_latest": "",
    "update_url": "",
    "update_checked_at": "",
    # Automatyczne powiadomienia (etap 2)
    "notify_enabled": "0",
    "notify_hour": "7",
    "notify_last_run": "",
    "notify_stage_soon": "1",
    "notify_stage_urgent": "1",
    "notify_stage_overdue": "1",
    "notify_repeat_days": "7",
    "notify_digest_empty": "0",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_security": "starttls",
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_from_name": "",
    "sms_provider": "none",
    "smsapi_token": "",
    "smsapi_from": "",
    "smsapi_test": "0",
    "android_mode": "local",
    "android_url": "",
    "android_user": "",
    "android_password": "",
    # Dostęp zdalny i HTTPS
    "remote_mode": "off",
    "public_url": "",
    "https_cert": "",
    "https_key": "",
    # Logowanie dwuetapowe
    "twofa_enabled": "0",
}

# Ustawienia z hasłami i kluczami – nie pokazujemy ich w formularzach ani w dzienniku zdarzeń.
SECRET_SETTINGS = {"smtp_password", "smsapi_token", "android_password"}

REMOTE_MODES = {
    "off": "Wyłączony – tylko sieć firmowa",
    "tailscale": "Tailscale (zalecane)",
    "cloudflare": "Cloudflare Tunnel",
    "proxy": "Własny serwer pośredniczący (np. Caddy, nginx)",
}

SMS_PROVIDERS = {
    "none": "Brak – SMS tylko ręcznie z telefonu",
    "smsapi": "SMSAPI.pl (bramka płatna)",
    "android": "Telefon z Androidem (SMS Gateway for Android)",
}


# Biblioteki dołączone do programu (karta „O programie”).
THIRD_PARTY = [
    ("Python", "PSF License", "https://www.python.org/"),
    ("FastAPI", "MIT", "https://fastapi.tiangolo.com/"),
    ("Starlette", "BSD-3-Clause", "https://www.starlette.io/"),
    ("Uvicorn", "BSD-3-Clause", "https://www.uvicorn.org/"),
    ("Jinja2", "BSD-3-Clause", "https://jinja.palletsprojects.com/"),
    ("Pydantic", "MIT", "https://docs.pydantic.dev/"),
    ("bcrypt", "Apache-2.0", "https://github.com/pyca/bcrypt"),
    ("python-multipart", "Apache-2.0", "https://github.com/Kludex/python-multipart"),
    ("openpyxl", "MIT", "https://openpyxl.readthedocs.io/"),
    ("segno (kody QR)", "BSD-3-Clause", "https://github.com/heuer/segno"),
    ("pystray (ikona w zasobniku Windows)", "LGPL-3.0", "https://github.com/moses-palmer/pystray"),
    ("Pillow", "MIT-CMU", "https://python-pillow.org/"),
]
