#!/usr/bin/env bash
set -euo pipefail
echo "LBC_BOOTSTRAP_004_START"
echo "host=$(hostname) user=$(id -un)"
echo "base_package_version=$(dpkg-query -W -f='${Version}' linux-bridge-console)"
echo "Waiting for verified GitHub prerelease v0.5.14..."
ready=false
for attempt in {1..18}; do
  if gh api "repos/Pcattache30/Linux-Bridge-Console/releases/tags/v0.5.14" --jq '.tag_name' >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 5
done
if [[ "$ready" != true ]]; then
  echo "ERROR: v0.5.14 has not been published."
  exit 2
fi
echo "Installing verified user-owned runtime without sudo..."
bash packaging/update-user.sh
APP="$HOME/.local/share/linux-bridge-console"
echo "active_runtime=$(readlink "$APP/current")"
echo "launcher=$(command -v lbc || true)"
echo "active_versions:"
find "$APP/versions" -mindepth 1 -maxdepth 1 -type d -printf '%f\n'
test "$(readlink "$APP/current")" = "versions/0.5.14"
test -x "$HOME/.local/bin/lbc"
test -f "$APP/current/usr/lib/linux-bridge-console/dashboard.py"
echo "LBC_BOOTSTRAP_004_SUCCESS"
