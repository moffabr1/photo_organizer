#!/bin/bash
# Photo Organizer — install desktop shortcut
# Run from the project root:
#   bash install/install_shortcut.sh

set -e

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$INSTALL_DIR")"
VENV_PYTHON="$APP_DIR/venv/bin/python"
MAIN="$APP_DIR/main.py"

# ── Sanity checks ──────────────────────────────────────────────────────────

if [ ! -f "$VENV_PYTHON" ]; then
  echo "ERROR: venv not found. Please run bash setup.sh first."
  exit 1
fi

if [ ! -f "$MAIN" ]; then
  echo "ERROR: main.py not found. Is this script in the install/ subfolder?"
  exit 1
fi

# ── Install icon ───────────────────────────────────────────────────────────

ICON_DIR_256="$HOME/.local/share/icons/hicolor/256x256/apps"
ICON_DIR_128="$HOME/.local/share/icons/hicolor/128x128/apps"
ICON_DIR_48="$HOME/.local/share/icons/hicolor/48x48/apps"
ICON_DIR_SVG="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$ICON_DIR_256" "$ICON_DIR_128" "$ICON_DIR_48" "$ICON_DIR_SVG"

cp "$INSTALL_DIR/icon_256.png" "$ICON_DIR_256/photo-organizer.png"
cp "$INSTALL_DIR/icon_128.png" "$ICON_DIR_128/photo-organizer.png"
cp "$INSTALL_DIR/icon_48.png"  "$ICON_DIR_48/photo-organizer.png"
cp "$INSTALL_DIR/icon.svg"     "$ICON_DIR_SVG/photo-organizer.svg"

echo "✓  Icons installed"

# ── Create .desktop file ───────────────────────────────────────────────────

DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_DIR/photo-organizer.desktop" << DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Photo Organizer
Comment=Fast multi-source photo browser and organizer
Exec=$VENV_PYTHON $MAIN
Icon=photo-organizer
Terminal=false
Categories=Graphics;Photography;Viewer;
Keywords=photo;image;organizer;gallery;viewer;video;
StartupNotify=true
StartupWMClass=photo-organizer
DESKTOP

chmod +x "$DESKTOP_DIR/photo-organizer.desktop"
echo "✓  Desktop entry created"

# ── Refresh icon cache ─────────────────────────────────────────────────────

if command -v gtk-update-icon-cache &>/dev/null; then
  gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

if command -v update-desktop-database &>/dev/null; then
  update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo ""
echo "✓  Photo Organizer shortcut installed."
echo "   It should appear in your app launcher immediately."
echo "   If not, log out and back in (or run: killall gnome-shell)"
echo ""
echo "   App location: $APP_DIR"
