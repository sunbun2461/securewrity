#!/usr/bin/env bash
# Install Securewrity for the current user on Debian / Kali / Ubuntu.
# Usage:  ./install.sh            install deps (sudo apt) + launcher + menu entry
#         ./install.sh --no-apt   skip apt (deps already installed)
#         ./install.sh --uninstall
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin/securewrity"
DESKTOP="$HOME/.local/share/applications/securewrity.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "$BIN" "$DESKTOP"
  echo "Launcher removed. Your notes are still in ~/.local/share/securewrity (delete it yourself if you want)."
  exit 0
fi

if [[ "${1:-}" != "--no-apt" ]]; then
  echo "==> Installing dependencies with apt (needs sudo)"
  sudo apt-get update
  sudo apt-get install -y python3 python3-pyqt6 python3-cryptography fonts-noto-color-emoji
fi

python3 - <<'EOF'
import sys
if sys.version_info < (3, 11):
    sys.exit("Securewrity needs Python 3.11+ (you have %s)" % sys.version.split()[0])
import PyQt6.QtWidgets, cryptography  # noqa
print("==> Python", sys.version.split()[0], "with PyQt6 and cryptography: OK")
EOF

mkdir -p "$(dirname "$BIN")" "$(dirname "$DESKTOP")"
cat > "$BIN" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m securewrity "\$@"
EOF
chmod +x "$BIN"

sed "s|@BIN@|$BIN|" "$APP_DIR/packaging/securewrity.desktop" > "$DESKTOP"
command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESKTOP")" || true

echo "==> Installed. Start it from your app menu (Securewrity) or run: securewrity"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "   (add ~/.local/bin to your PATH to use the 'securewrity' command)";; esac
