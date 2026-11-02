"""Niezapominajka – uruchamianie serwera: konsola, ikona w zasobniku (Windows) i okno (Linux).

Copyright (C) 2026 Maksymilian Staszewski – licencja GNU AGPL v3 lub nowsza.
"""
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from . import config, db, services as svc


def _scheme():
    s = db.get_settings()
    cert, key = s.get("https_cert") or "", s.get("https_key") or ""
    if cert and key and Path(cert).exists() and Path(key).exists():
        return "https", cert, key
    return "http", None, None


def local_url():
    scheme, _, _ = _scheme()
    return f"{scheme}://localhost:{config.PORT}"


def lan_url():
    scheme, _, _ = _scheme()
    return f"{scheme}://{svc.lan_address()}:{config.PORT}"


def _port_busy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", config.PORT)) == 0


def _is_ours():
    """Czy na porcie działa już Niezapominajka (np. druga próba uruchomienia)."""
    for scheme in ("http", "https"):
        try:
            import ssl
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(f"{scheme}://127.0.0.1:{config.PORT}/manifest.webmanifest", timeout=2, context=ctx) as r:
                return config.APP_NAME.encode() in r.read(4000)
        except Exception:
            continue
    return False


def make_server():
    db.init()
    scheme, cert, key = _scheme()
    from .main import app
    kw = {}
    if cert:
        kw.update(ssl_certfile=cert, ssl_keyfile=key)
    cfg = uvicorn.Config(app, host=config.HOST, port=config.PORT, proxy_headers=True, forwarded_allow_ips="127.0.0.1",
                         log_level="warning", log_config=None if sys.stdout is None else uvicorn.config.LOGGING_CONFIG, **kw)
    return uvicorn.Server(cfg)


def banner():
    lines = [f"{config.APP_NAME} {config.APP_VERSION}", f"Dane programu: {config.DATA_DIR}",
             f"Na tym komputerze: {local_url()}"]
    if config.HOST not in ("127.0.0.1", "localhost"):
        lines.append(f"W sieci firmowej (telefon, inne komputery): {lan_url()}")
    return lines


def _message(title, text):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
            return
        except Exception:
            pass
    print(f"{title}: {text}")


# ---------------------------------------------------------------- konsola

def run_console(open_browser=False):
    if _port_busy():
        print(f"Port {config.PORT} jest zajęty. Program już działa albo port używa inny program. "
              f"Uruchom z opcją --port, np. --port 8080.")
        return 1
    server = make_server()
    print()
    for line in banner():
        print("  " + line)
    print("  Zatrzymanie: Ctrl+C\n")
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(local_url())).start()
    server.run()
    return 0


# ---------------------------------------------------------------- tryb okienkowy

def _open_folder(path):
    path = str(path)
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            env = dict(os.environ)
            for k in ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH"):
                env.pop(k, None)
            subprocess.Popen(["xdg-open", path], env=env)
    except Exception as exc:  # pragma: no cover
        _message(config.APP_NAME, f"Nie można otworzyć folderu: {exc}")


def _open_browser(url):
    if os.environ.get("APPIMAGE"):
        # Przeglądarka nie może dziedziczyć bibliotek z obrazu AppImage.
        env = dict(os.environ)
        for k in ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY"):
            env.pop(k, None)
        try:
            subprocess.Popen(["xdg-open", url], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(url)


def run_desktop(open_browser=True):
    if _port_busy():
        if _is_ours():
            _open_browser(local_url())
            return 0
        _message(config.APP_NAME, f"Port {config.PORT} jest zajęty przez inny program. "
                                  f"Uruchom Niezapominajkę z opcją --port, np. --port 8080.")
        return 1
    server = make_server()
    t = threading.Thread(target=server.run, name="serwer", daemon=True)
    t.start()
    for _ in range(150):
        if server.started or not t.is_alive():
            break
        time.sleep(0.1)
    if not server.started:
        _message(config.APP_NAME, f"Nie udało się uruchomić serwera. Szczegóły w pliku {config.LOG_FILE}.")
        return 1
    if open_browser:
        _open_browser(local_url())

    def stop():
        server.should_exit = True
        t.join(timeout=10)

    if os.name == "nt":
        try:
            return _tray(stop)
        except Exception as exc:
            print(f"Ikona w zasobniku niedostępna: {exc}")
    try:
        return _window(stop)
    except Exception as exc:
        print(f"Okno niedostępne ({exc}) – serwer działa w tle. Zatrzymanie: Ctrl+C.")
        try:
            while t.is_alive():
                t.join(1)
        except KeyboardInterrupt:
            stop()
        return 0


def _icon_path(name):
    return config.BASE_DIR / "static" / "icons" / name


def _tray(stop):
    import pystray
    from PIL import Image

    image = Image.open(_icon_path("icon-192.png"))

    def show_address(icon, item):
        threading.Thread(target=_show_address, daemon=True).start()

    def _show_address():
        _message(config.APP_NAME, "Adres dla telefonu i innych komputerów w sieci firmowej:\n\n"
                 f"{lan_url()}\n\nNa telefonie otwórz go w przeglądarce i wybierz „Dodaj do ekranu głównego”.")

    def quit_app(icon, item):
        icon.visible = False
        stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Otwórz Niezapominajkę", lambda i, it: _open_browser(local_url()), default=True),
        pystray.MenuItem("Adres dla telefonu", show_address),
        pystray.MenuItem("Folder danych", lambda i, it: _open_folder(config.DATA_DIR)),
        pystray.MenuItem("Pomoc", lambda i, it: _open_browser(local_url() + "/pomoc")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Zakończ", quit_app),
    )
    icon = pystray.Icon("niezapominajka", image, f"{config.APP_NAME} {config.APP_VERSION} – działa", menu)
    icon.run()
    return 0


def _window(stop):
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(config.APP_NAME)
    root.resizable(False, False)
    try:
        root.iconphoto(True, tk.PhotoImage(file=str(_icon_path("icon-192.png"))).subsample(3, 3))
    except Exception:
        pass
    frm = ttk.Frame(root, padding=18)
    frm.grid()
    ttk.Label(frm, text=f"{config.APP_NAME} {config.APP_VERSION}", font=("TkDefaultFont", 13, "bold")).grid(column=0, row=0, columnspan=3, sticky="w")
    ttk.Label(frm, text="Program działa. Zamknięcie tego okna zatrzymuje program.").grid(column=0, row=1, columnspan=3, sticky="w", pady=(2, 10))
    ttk.Label(frm, text="Na tym komputerze:").grid(column=0, row=2, sticky="w")
    e1 = ttk.Entry(frm, width=36)
    e1.insert(0, local_url())
    e1.configure(state="readonly")
    e1.grid(column=1, row=2, columnspan=2, sticky="we", pady=2)
    ttk.Label(frm, text="Telefon / sieć firmowa:").grid(column=0, row=3, sticky="w")
    e2 = ttk.Entry(frm, width=36)
    e2.insert(0, lan_url())
    e2.configure(state="readonly")
    e2.grid(column=1, row=3, columnspan=2, sticky="we", pady=2)
    ttk.Label(frm, text=f"Dane: {config.DATA_DIR}", foreground="#65708A").grid(column=0, row=4, columnspan=3, sticky="w", pady=(6, 12))

    def quit_app():
        root.destroy()

    ttk.Button(frm, text="Otwórz w przeglądarce", command=lambda: _open_browser(local_url())).grid(column=0, row=5, sticky="w")
    ttk.Button(frm, text="Folder danych", command=lambda: _open_folder(config.DATA_DIR)).grid(column=1, row=5)
    ttk.Button(frm, text="Zakończ", command=quit_app).grid(column=2, row=5, sticky="e")
    root.protocol("WM_DELETE_WINDOW", quit_app)
    root.mainloop()
    stop()
    return 0
