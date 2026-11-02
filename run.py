"""Niezapominajka – uruchomienie programu.

    python run.py                    serwer w oknie konsoli (Ctrl+C zatrzymuje)
    python run.py --okno             tryb okienkowy: ikona w zasobniku (Windows) / małe okno (Linux)
    python run.py --port 8080 --dane /sciezka/do/danych

Copyright (C) 2026 Maksymilian Staszewski
Program jest wolnym oprogramowaniem na licencji GNU AGPL v3 lub nowszej (plik LICENSE).
"""
import argparse
import os
import sys


def parse_args():
    frozen = bool(getattr(sys, "frozen", False)) or bool(os.environ.get("APPIMAGE"))
    p = argparse.ArgumentParser(prog="niezapominajka", description="Niezapominajka – przypominajka ważnych terminów w firmie")
    p.add_argument("--host", help="adres nasłuchu (domyślnie 0.0.0.0 – cała sieć firmowa; 127.0.0.1 – tylko ten komputer)")
    p.add_argument("--port", type=int, help="port (domyślnie 8000)")
    p.add_argument("--dane", help="folder danych programu")
    p.add_argument("--okno", action="store_true", default=None, help="tryb okienkowy (ikona w zasobniku / okno)")
    p.add_argument("--serwer", action="store_true", help="tryb serwera bez okna (np. usługa systemowa)")
    p.add_argument("--bez-przegladarki", action="store_true", help="nie otwieraj przeglądarki po starcie")
    p.add_argument("--wersja", action="store_true", help="pokaż wersję i zakończ")
    a = p.parse_args()
    if a.okno is None:
        a.okno = frozen and not a.serwer
    if a.serwer:
        a.okno = False
    return a


def main():
    args = parse_args()
    if args.host:
        os.environ["NIEZAPOMINAJKA_HOST"] = args.host
    if args.port:
        os.environ["NIEZAPOMINAJKA_PORT"] = str(args.port)
    if args.dane:
        os.environ["NIEZAPOMINAJKA_DANE"] = args.dane

    from app import config
    if args.wersja:
        print(f"{config.APP_NAME} {config.APP_VERSION}")
        return 0

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Wersja okienkowa exe nie ma konsoli – komunikaty trafiają do pliku dziennika.
    if sys.stdout is None or sys.stderr is None:
        log = open(config.LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log

    from app import launcher
    if args.okno:
        return launcher.run_desktop(open_browser=not args.bez_przegladarki)
    return launcher.run_console(open_browser=False)


if __name__ == "__main__":
    sys.exit(main() or 0)
