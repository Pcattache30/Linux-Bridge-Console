#!/usr/bin/env bash
set -euo pipefail
echo "LBC_LEGACY_CLEANUP_005_START"
APP="$HOME/.local/share/linux-bridge-console"
VERSION="0.5.14"
CURRENT="$(readlink "$APP/current" 2>/dev/null || true)"
[[ "$CURRENT" == "versions/$VERSION" ]] || { echo "STOP: unexpected active runtime $CURRENT"; exit 2; }
RUNTIME="$APP/current/usr/lib/linux-bridge-console"
[[ -f "$RUNTIME/dashboard.py" && -f "$RUNTIME/runner.py" && -f "$RUNTIME/update-user.sh" ]] || { echo "STOP: active runtime incomplete"; exit 2; }
python3 - "$RUNTIME" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1])
for f in root.glob("*.py"):
    compile(f.read_bytes(), str(f), "exec")
print("ACTIVE_RUNTIME_PYTHON_VALIDATED")
PY

echo "Removing obsolete per-user runtime versions (preserving $VERSION)..."
find "$APP/versions" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' |
while IFS= read -r item; do
  if [[ "$item" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$item" != "$VERSION" ]]; then
    rm -rf -- "$APP/versions/$item"
    echo "removed_user_version=$item"
  fi
done

# Retire obsolete source launcher without deleting the user's source project.
DEV_LAUNCHER="$HOME/Projects/Linux-Bridge-Console/lbc"
OLD_LINK="$HOME/.local/bin/lbc"
if [[ -f "$OLD_LINK" ]] && grep -Fq 'exec bash "' "$OLD_LINK" && grep -Fq '/lbc" "$@"' "$OLD_LINK"; then
  echo "legacy_launcher_found"
fi

# Install a single launcher that uses the active verified runtime directly.
TMP="$HOME/.local/bin/lbc.cleanup.$$"
mkdir -p "$HOME/.local/bin"
cat > "$TMP" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
APP="$HOME/.local/share/linux-bridge-console/current/usr/lib/linux-bridge-console"
if [[ "${1:-}" == "update" ]]; then
  shift
  exec bash "$APP/update-user.sh" "$@"
fi
exec python3 "$APP/dashboard.py" "$@"
SH
chmod 755 "$TMP"
mv -f "$TMP" "$HOME/.local/bin/lbc"
echo "active_launcher=$HOME/.local/bin/lbc"

# Remove only the known old developer entry point; leave source/repository content intact.
if [[ -f "$DEV_LAUNCHER" && ! -L "$DEV_LAUNCHER" ]]; then
  if grep -Fq 'tools/update.sh' "$DEV_LAUNCHER" && grep -Fq 'dashboard.py' "$DEV_LAUNCHER"; then
    rm -- "$DEV_LAUNCHER"
    echo "removed_legacy_dev_entrypoint=$DEV_LAUNCHER"
  else
    echo "legacy_dev_entrypoint_not_recognized_skipped"
  fi
fi

# The active runtime is user-owned and independent of the obsolete system package.
if dpkg-query -W -f='${Status}' linux-bridge-console 2>/dev/null | grep -q '^install ok installed$'; then
  echo "legacy_system_package=$(dpkg-query -W -f='${Version}' linux-bridge-console)"
  if sudo -n true 2>/dev/null; then
    echo "Removing obsolete system Debian package..."
    sudo -n apt-get remove -y linux-bridge-console
    echo "removed_system_package=yes"
  else
    echo "removed_system_package=no"
    echo "BLOCKED: sudo authorization required to uninstall obsolete dpkg package"
  fi
else
  echo "obsolete_system_package_not_installed"
fi

echo "active_runtime=$(readlink "$APP/current")"
echo "remaining_user_versions:"
find "$APP/versions" -mindepth 1 -maxdepth 1 -type d -printf '%f\n'
echo "active_launcher_exists=$(test -x "$HOME/.local/bin/lbc" && echo yes || echo no)"
echo "system_package_status=$(dpkg-query -W -f='${Status} ${Version}' linux-bridge-console 2>/dev/null || echo not-installed)"
echo "LBC_LEGACY_CLEANUP_005_COMPLETE"
