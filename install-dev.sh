#!/usr/bin/env bash
set -euo pipefail
SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
SERVICE="$HOME/.config/systemd/user"
mkdir -p "$BIN" "$SERVICE"
chmod +x "$SOURCE/lbc"
ln -sfn "$SOURCE/lbc" "$BIN/lbc"
cat > "$SERVICE/linux-bridge-console.service" <<EOF
[Unit]
Description=Linux Bridge Console background worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$SOURCE
ExecStart=/usr/bin/python3 $SOURCE/src/linux_bridge_console/worker.py --repo Pcattache30/Linux-Bridge-Console --interval 15
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now linux-bridge-console.service
echo "Worker installed. Automatic execution remains DISABLED."
echo "Run $BIN/lbc | $BIN/lbc status | $BIN/lbc update"
echo "Add $BIN to PATH if required."
