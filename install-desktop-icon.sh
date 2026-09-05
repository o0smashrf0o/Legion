#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$ROOT/legion-gui"

ICON_256="$ROOT/gui/static/img/icons/legion-hud-256.png"
ICON_48="$ROOT/gui/static/img/icons/legion-hud-48.png"
ICON_FULL="$ROOT/Legion-HUD.png"
ICON_SRC="$ICON_256"
[[ -f "$ICON_SRC" ]] || ICON_SRC="$ICON_FULL"
[[ -f "$ICON_SRC" ]] || { echo "missing Legion HUD icon"; exit 1; }

mkdir -p "$HOME/.local/share/pixmaps" \
  "$HOME/.local/share/icons/hicolor/256x256/apps" \
  "$HOME/.local/share/icons/hicolor/48x48/apps"
cp "$ICON_SRC" "$HOME/.local/share/pixmaps/legion-hud.png"
cp "$ICON_SRC" "$HOME/.local/share/icons/hicolor/256x256/apps/legion-hud.png"
if [[ -f "$ICON_48" ]]; then
  cp "$ICON_48" "$HOME/.local/share/icons/hicolor/48x48/apps/legion-hud.png"
fi

if sudo -n true 2>/dev/null; then
  sudo mkdir -p /usr/share/pixmaps \
    /usr/share/icons/hicolor/256x256/apps \
    /usr/share/icons/hicolor/48x48/apps
  sudo cp "$ICON_SRC" /usr/share/pixmaps/legion-hud.png
  sudo cp "$ICON_SRC" /usr/share/icons/hicolor/256x256/apps/legion-hud.png
  if [[ -f "$ICON_48" ]]; then
    sudo cp "$ICON_48" /usr/share/icons/hicolor/48x48/apps/legion-hud.png
  fi
  sudo chmod 644 /usr/share/pixmaps/legion-hud.png
  sudo gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
fi

if [[ -f /usr/share/pixmaps/legion-hud.png ]]; then
  ICON_KEY=legion-hud
else
  ICON_KEY="$ICON_SRC"
fi

DESK="$HOME/Desktop/Legion-HUD.desktop"
if [[ -d "$HOME/Desktop" ]]; then
  cat > "$DESK" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Legion HUD
Comment=Sentinel Network Control HUD
Exec=$ROOT/legion-gui
TryExec=$ROOT/legion-gui
Icon=$ICON_KEY
Terminal=false
StartupNotify=false
Categories=Network;Utility;
EOF
  chmod +x "$DESK"
  gio set "$DESK" metadata::trusted true 2>/dev/null || true
fi
