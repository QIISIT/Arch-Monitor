#!/usr/bin/env bash
# Arch Monitor installer. Usage: bash install-archmon.sh   (remove: bash install-archmon.sh --remove)
set -euo pipefail
APP=archmon
DIR="$HOME/.local/share/$APP"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICON="$HOME/.local/share/icons/hicolor/scalable/apps"

case "${1:-}" in ""|--remove) ;; *) echo "Usage: bash $0 [--remove]" >&2; exit 2 ;; esac
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
awk 'f;/^#__PAYLOAD__$/{f=1}' "$0" | base64 -d > "$stage/payload.tar.gz"
printf '%s  %s\n' '@PAYLOAD_SHA256@' "$stage/payload.tar.gz" | sha256sum -c --status || {
  echo "Installer archive is damaged. Nothing has been installed or removed." >&2
  exit 1
}
tar xzf "$stage/payload.tar.gz" -C "$stage"

if [ "${1:-}" = "--remove" ]; then
  if [ -d /usr/local/lib/archmon ] || [ -f /etc/systemd/system/archmon-fans.service ] ||
     [ -d /run/archmon-fans ] || [ -d /etc/archmon ]; then
    # Используем восстановление из новой версии даже при удалении старой службы.
    if ! sudo /bin/sh -s -- "$stage/archmon/fand.py" <<'REMOVE_FANS'
set -eu
unit=archmon-fans.service
load_state=$(systemctl show --property=LoadState --value "$unit")
if [ "$load_state" != "not-found" ]; then
  systemctl disable "$unit"
  systemctl stop "$unit" || true
  active_state=$(systemctl show --property=ActiveState --value "$unit")
  case "$active_state" in inactive|failed) ;; *) echo "Fan service is still running." >&2; exit 1 ;; esac
fi
/usr/bin/python3 -I "$1" --restore
# В случае ошибки восстановления set -e прерывает удаление до удаления файлов.
rm -f /etc/systemd/system/archmon-fans.service /etc/polkit-1/rules.d/50-archmon-fans.rules
rm -f /usr/local/lib/archmon/fand.py /usr/local/lib/archmon/fanctl /usr/local/lib/archmon/installed.stamp
rm -f /etc/archmon/fans.json /etc/archmon/fans.json.new /run/archmon-fans/original.json.new
rm -rf /usr/local/lib/archmon/__pycache__
rmdir /usr/local/lib/archmon /etc/archmon /run/archmon-fans 2>/dev/null || true
systemctl daemon-reload
REMOVE_FANS
    then
      echo "Removal stopped: fan recovery was not confirmed. Files retained; correct the error and retry." >&2
      exit 1
    fi
  fi
  pkill -f "python3 -m [a]rchmon" 2>/dev/null || true
  rm -rf "$DIR" "$BIN/$APP" "$APPS/$APP.desktop" "$ICON/$APP.svg"
  update-desktop-database "$APPS" 2>/dev/null || true
  echo "Arch Monitor removed."
  exit 0
fi

sudo pacman -S --needed --noconfirm python-pyqt6 python-psutil qt6-svg
# Закрыть уже запущенную копию (иначе она живёт в трее со старым кодом, а новый запуск лишь покажет её окно)
pkill -f "python3 -m [a]rchmon" 2>/dev/null && echo "Closed the running copy of Arch Monitor." || true
mkdir -p "$DIR" "$BIN" "$APPS" "$ICON"
rm -rf "$DIR/archmon" "$DIR/archmon.py"
tar xzf "$stage/payload.tar.gz" -C "$DIR"

cat > "$BIN/$APP" <<LAUNCH
#!/bin/sh
cd "$DIR" && exec python3 -m archmon "\$@"
LAUNCH
chmod +x "$BIN/$APP"

cat > "$ICON/$APP.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<rect width="256" height="256" rx="56" fill="#0d1218"/>
<rect x="44" y="120" width="32" height="92" rx="8" fill="#1793D1"/>
<rect x="92" y="72" width="32" height="140" rx="8" fill="#1793D1"/>
<rect x="140" y="100" width="32" height="112" rx="8" fill="#1793D1"/>
<rect x="188" y="148" width="32" height="64" rx="8" fill="#e5c07b"/>
<rect x="44" y="44" width="176" height="8" rx="4" fill="#232d39"/>
</svg>
SVG

cat > "$APPS/$APP.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Arch Monitor
Comment=Processes and system load, htop-style
Exec=$BIN/$APP
Icon=$APP
Terminal=false
Categories=System;Monitor;
Keywords=htop;top;processes;monitor;
DESK

update-desktop-database "$APPS" 2>/dev/null || true
kbuildsycoca6 >/dev/null 2>&1 || true
echo "Done. Find 'Arch Monitor' in the app menu, or run: archmon"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Note: add $BIN to your PATH to run 'archmon' from a terminal." ;; esac
exit 0
