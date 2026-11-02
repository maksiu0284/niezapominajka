#!/usr/bin/env bash
# Niezapominajka – uruchomienie ze źródeł na Linux / macOS
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Pierwsze uruchomienie: tworzę środowisko Python..."
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/python run.py "$@"
