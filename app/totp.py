"""Niezapominajka – kody jednorazowe TOTP (RFC 6238), zgodne z Google Authenticator, Microsoft Authenticator, Aegis."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, counter: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** DIGITS)).zfill(DIGITS)


def verify(secret: str, code: str, last_counter=None, window: int = 1, now=None):
    """Zwraca licznik użytego kodu albo None. Kod raz użyty nie zadziała ponownie."""
    if not secret or not code:
        return None
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != DIGITS:
        return None
    counter = int((now or time.time()) // STEP)
    for c in range(counter - window, counter + window + 1):
        if last_counter is not None and c <= int(last_counter):
            continue
        if hmac.compare_digest(code_at(secret, c), code):
            return c
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def qr_svg(data: str) -> str:
    """Kod QR jako SVG (biblioteka segno). Gdy brak biblioteki – pusty napis."""
    try:
        import segno
    except ImportError:
        return ""
    import io
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=5, border=2, dark="#1B2A4A", light="#FFFFFF",
                                     xmldecl=False, svgns=True)
    return buf.getvalue().decode()


def pretty(secret: str) -> str:
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
