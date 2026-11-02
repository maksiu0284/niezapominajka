#!/usr/bin/env bash
# Niezapominajka – odinstalowanie serwera. Dane w /var/lib/niezapominajka zostają,
# chyba że podasz --usun-dane.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Uruchom przez sudo"; exit 1; fi
systemctl disable --now niezapominajka 2>/dev/null || true
rm -f /etc/systemd/system/niezapominajka.service
systemctl daemon-reload
rm -rf /opt/niezapominajka
if [ "${1:-}" = "--usun-dane" ]; then
  rm -rf /var/lib/niezapominajka
  userdel niezapominajka 2>/dev/null || true
  echo "Usunięto program i dane."
else
  echo "Usunięto program. Dane zostały w /var/lib/niezapominajka."
fi
