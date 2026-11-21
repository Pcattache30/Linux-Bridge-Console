#!/usr/bin/env bash
set -euo pipefail
SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
SERVICE="$HOME/.config/systemd/user"
mkdir -p "$BIN" "$SERVICE"
cat > "$BIN/lbc" <<EOF
#!/usr/bin/env bash
exec python3 "$SOURCE/src/linux_bridge_console/dashboard.py" "\$@"
EOF
chmod 755 "$BIN/lbc"
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
echo "User worker installed (auto-run DISABLED)."
echo "Dashboard: $BIN/lbc"
echo "Status: systemctl --user status linux-bridge-console --no-pager"
echo "NOTE: To run after logout, an administrator can enable linger for this user."
