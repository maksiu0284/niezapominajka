#!/usr/bin/env bash
# Niezapominajka – budowa AppImage i paczki serwerowej tar.gz (x86_64).
# Wymaga: curl, tar, file. Python jest pobierany jako python-build-standalone.
# Użycie: packaging/linux/build_linux.sh [katalog_wyjściowy]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$ROOT/dist}"
VER="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' "$ROOT/app/config.py")"
PBS_URL="${PBS_URL:-https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz}"
AIT_URL="${AIT_URL:-https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage}"
WORK="$ROOT/build/linux"
mkdir -p "$WORK" "$OUT"
cd "$WORK"
[ -f pbs.tgz ] || curl -fL -o pbs.tgz "$PBS_URL"
[ -f appimagetool ] || { curl -fL -o appimagetool "$AIT_URL"; chmod +x appimagetool; }

copy_app() {  # $1 = katalog docelowy
  mkdir -p "$1"
  cp -a "$ROOT/run.py" "$ROOT/LICENSE" "$ROOT/README.md" "$1/"
  cp -a "$ROOT/app" "$1/app"
  find "$1" -name __pycache__ -type d -prune -exec rm -rf {} +
}
make_python() {  # $1 = katalog docelowy python
  rm -rf "$1"; mkdir -p "$(dirname "$1")"
  tar -xzf pbs.tgz -C "$(dirname "$1")"
  [ "$(basename "$1")" = python ] || mv "$(dirname "$1")/python" "$1"
  "$1/bin/python3" -m pip install --no-cache-dir --disable-pip-version-check -q -r "$ROOT/requirements.txt"
  rm -rf "$1/lib/python3."*/test "$1/lib/python3."*/idlelib "$1/lib/python3."*/ensurepip
  find "$1" -name __pycache__ -type d -prune -exec rm -rf {} +
}

echo "== AppImage"
rm -rf AppDir; mkdir -p AppDir/usr
make_python AppDir/usr/python
copy_app AppDir/usr/app
cp "$ROOT/packaging/linux/AppRun" AppDir/AppRun; chmod +x AppDir/AppRun
cp "$ROOT/packaging/linux/niezapominajka.desktop" AppDir/
cp "$ROOT/packaging/linux/niezapominajka.png" AppDir/niezapominajka.png
cp AppDir/niezapominajka.png AppDir/.DirIcon
mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps AppDir/usr/share/applications
cp AppDir/niezapominajka.png AppDir/usr/share/icons/hicolor/256x256/apps/
cp AppDir/niezapominajka.desktop AppDir/usr/share/applications/
ARCH=x86_64 ./appimagetool --appimage-extract-and-run --no-appstream AppDir "$OUT/Niezapominajka-$VER-x86_64.AppImage"

echo "== Serwer tar.gz"
S="niezapominajka-$VER-linux-serwer"
rm -rf "$S"; mkdir -p "$S"
make_python "$S/python"
copy_app "$S/app"
cp "$ROOT/packaging/linux/"{install.sh,uninstall.sh,niezapominajka.service} "$S/"
cp "$ROOT/LICENSE" "$ROOT/README.md" "$S/"
chmod +x "$S/install.sh" "$S/uninstall.sh"
tar -czf "$OUT/$S.tar.gz" "$S"
echo "Gotowe: $OUT"
ls -la "$OUT"
