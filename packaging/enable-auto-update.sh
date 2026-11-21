#!/usr/bin/env bash
set -euo pipefail
[[ "$(id -u)" -eq 0 ]] || { echo "Requires sudo" >&2; exit 1; }
USER_NAME="${SUDO_USER:-}"
[[ "$USER_NAME" =~ ^[a-z_][a-z0-9_-]*$ && "$USER_NAME" != root ]] || {
 echo "Run: sudo /usr/lib/linux-bridge-console/enable-auto-update.sh (as a regular user)" >&2
 exit 1
}
getent passwd "$USER_NAME" >/dev/null
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
[[ -f "$USER_HOME/.config/gh/hosts.yml" ]] || {
 echo "Authenticate GitHub as $USER_NAME before enabling automatic updates." >&2
 exit 1
}
install -d -m 0755 /etc/linux-bridge-console
printf '%s\n' "$USER_NAME" > /etc/linux-bridge-console/update-user
chown root:root /etc/linux-bridge-console/update-user
chmod 0644 /etc/linux-bridge-console/update-user
systemctl daemon-reload
systemctl enable --now lbc-auto-update.timer
echo "Automatic LBC package updates ENABLED (checks every minute)."
echo "The updater will use GitHub authentication belonging to $USER_NAME."
echo "A running job will block installation until it completes."
