#!/usr/bin/env bash
# Per-user install without root, into ~/.local. On its first run the tray adds
# itself to ~/.config/autostart.
# For a system-wide install: `sudo make install PREFIX=/usr`.
set -euo pipefail
cd "$(dirname "$0")"

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

if [ -e /usr/bin/waydroid-tray ]; then
    echo "waydroid-tray is already installed system-wide (/usr/bin/waydroid-tray)." >&2
    exit 1
fi

make --no-print-directory install PREFIX="$HOME/.local" DATADIR="$DATA"

# Start it now (a running copy re-execs itself when its file is replaced).
if ! pgrep -f "$HOME/.local/bin/waydroid-tray" >/dev/null; then
    setsid -f "$HOME/.local/bin/waydroid-tray" >/dev/null 2>&1
fi
echo "Installed. Waydroid Tray is running and will start at every login."
