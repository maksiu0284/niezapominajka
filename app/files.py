"""Bezpieczna obsługa przesyłanych plików: rozpoznawanie typu po zawartości.

Typ pliku ustala serwer – na podstawie rozszerzenia z listy dozwolonych i pierwszych bajtów pliku.
Typ podany przez przeglądarkę wysyłającą jest ignorowany.
"""
from pathlib import Path

# Rozszerzenie -> typ MIME podawany przy pobieraniu.
MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".rtf": "application/rtf",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}

# Typy, których nigdy nie przyjmujemy (mogą zawierać skrypty wykonywane przez przeglądarkę).
BLOCKED_EXTENSIONS = {".svg", ".svgz", ".htm", ".html", ".xhtml", ".xht", ".shtml", ".xml", ".xsl", ".js", ".mjs",
                      ".hta", ".php", ".swf", ".mht", ".mhtml"}

# W przeglądarce otwieramy tylko te typy (zdjęcia i PDF); reszta jest wyłącznie do pobrania.
INLINE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}

_ZIP = (b"PK\x03\x04",)
_OLE = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"heif", b"avif"}


def ext_of(name) -> str:
    return Path(name or "").suffix.lower()


def _is_text(data: bytes) -> bool:
    sample = data[:65536]
    if b"\x00" in sample:
        return False
    for enc in ("utf-8", "cp1250"):
        try:
            sample.decode(enc)
            return True
        except UnicodeDecodeError:
            continue
    return False


def matches(ext: str, data: bytes) -> bool:
    """Czy zawartość pliku zgadza się z rozszerzeniem."""
    head = data[:64]
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext in (".heic", ".heif"):
        return head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS
    if ext == ".pdf":
        return head.startswith(b"%PDF-")
    if ext in (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"):
        return head.startswith(_ZIP)
    if ext in (".doc", ".xls", ".ppt"):
        return head.startswith(_OLE)
    if ext == ".rtf":
        return head.startswith(b"{\\rtf")
    if ext in (".txt", ".csv"):
        return _is_text(data)
    return False


def check_upload(filename: str, data: bytes, allowed: set):
    """Zwraca typ MIME albo rzuca ValueError z komunikatem dla użytkownika."""
    ext = ext_of(filename)
    if ext in BLOCKED_EXTENSIONS or ext not in allowed or ext not in MIME_BY_EXT:
        raise ValueError(f"Niedozwolony typ pliku: {filename}")
    if not matches(ext, data):
        raise ValueError(f"Zawartość pliku {filename} nie pasuje do jego rozszerzenia ({ext}). Plik odrzucono.")
    return MIME_BY_EXT[ext]


def serve_info(stored_path: Path, original_name: str):
    """(mime, czy_można_otworzyć_w_przeglądarce) dla pliku zapisanego na serwerze.

    Typ zawsze wynika z rozszerzenia i sprawdzenia zawartości – nigdy z danych zapisanych przy wysyłce.
    Plik, którego zawartość nie pasuje do rozszerzenia, idzie wyłącznie do pobrania jako dane binarne.
    """
    ext = ext_of(original_name)
    stored_ext = ext_of(stored_path.name)
    try:
        with open(stored_path, "rb") as fh:
            data = fh.read(65536)
    except OSError:
        data = b""
    if ext != stored_ext or ext not in MIME_BY_EXT or ext in BLOCKED_EXTENSIONS or not matches(ext, data):
        return "application/octet-stream", False
    return MIME_BY_EXT[ext], ext in INLINE_EXTENSIONS


# Nagłówki dla każdego pobieranego pliku: przeglądarka nie zgaduje typu, a ewentualny
# skrypt nie ma dostępu do programu (osobny, pusty kontekst bez uprawnień).
FILE_CSP_SANDBOX = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
# Wbudowana przeglądarka PDF w Chrome/Edge nie działa w trybie „sandbox”, dlatego dla PDF
# stosujemy tylko blokadę skryptów i ramek – PDF nie uruchamia skryptów strony.
FILE_CSP_PDF = "default-src 'none'; img-src 'self' data: blob:; style-src 'unsafe-inline'; object-src 'self'; frame-ancestors 'self'"


def file_headers(mime: str, inline: bool, filename: str, quote) -> dict:
    disp = "inline" if inline else "attachment"
    return {
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(filename)}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": FILE_CSP_PDF if mime == "application/pdf" else FILE_CSP_SANDBOX,
        "Cache-Control": "private, no-store",
    }


def fix_stored_types(db, upload_dir: Path):
    """Przy starcie: poprawia typy załączników zapisanych przez starsze wersje."""
    changed = 0
    for a in db.query("SELECT id, original_name, stored_name, mime FROM attachments"):
        mime, _ = serve_info(upload_dir / Path(a["stored_name"]).name, a["original_name"])
        if a["mime"] != mime:
            db.execute("UPDATE attachments SET mime=? WHERE id=?", (mime, a["id"]))
            changed += 1
    return changed
