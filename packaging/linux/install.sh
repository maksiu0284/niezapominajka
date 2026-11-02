#!/usr/bin/env bash
# Niezapominajka – instalacja serwera (Debian / Ubuntu / inne z systemd)
# Użycie: sudo ./install.sh [--port 8000]
set -euo pipefail
PORT=8000
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    *) echo "Nieznana opcja: $1"; exit 1 ;;
  esac
done
if [ "$(id -u)" -ne 0 ]; then echo "Uruchom przez sudo: sudo ./install.sh"; exit 1; fi
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/niezapominajka
DATA=/var/lib/niezapominajka

echo "Instaluję Niezapominajkę w $DEST, dane: $DATA, port: $PORT"
id niezapominajka >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin niezapominajka
systemctl stop niezapominajka 2>/dev/null || true
rm -rf "$DEST.new"
mkdir -p "$DEST.new"
cp -a "$HERE/python" "$HERE/app" "$DEST.new/"
cp -a "$HERE/uninstall.sh" "$HERE/LICENSE" "$HERE/README.md" "$DEST.new/" 2>/dev/null || true
rm -rf "$DEST.old"; [ -d "$DEST" ] && mv "$DEST" "$DEST.old"
mv "$DEST.new" "$DEST"; rm -rf "$DEST.old"
mkdir -p "$DATA"; chown -R niezapominajka:niezapominajka "$DATA"; chmod 750 "$DATA"
sed "s/NIEZAPOMINAJKA_PORT=8000/NIEZAPOMINAJKA_PORT=$PORT/" "$HERE/niezapominajka.service" > /etc/systemd/system/niezapominajka.service
systemctl daemon-reload
systemctl enable --now niezapominajka
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow "$PORT/tcp" comment "Niezapominajka" || true
fi
sleep 2
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
systemctl --no-pager --lines=0 status niezapominajka || true
echo
echo "Gotowe. Otwórz w przeglądarce: http://${IP:-adres-serwera}:$PORT"
echo "Dziennik: journalctl -u niezapominajka -f"
