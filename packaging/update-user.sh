#!/usr/bin/env bash
# Install LBC releases into this user's home; never require root.
set -euo pipefail
REPO="Pcattache30/Linux-Bridge-Console"
APP="$HOME/.local/share/linux-bridge-console"
VERSIONS="$APP/versions"
BIN="$HOME/.local/bin"
LOCK="$APP/runtime-update.lock"
mkdir -p "$VERSIONS" "$BIN"
exec 9>"$LOCK"
flock -x 9
for exe in gh dpkg-deb sha256sum python3; do command -v "$exe" >/dev/null || { echo "Missing $exe" >&2; exit 2; }; done
gh auth status >/dev/null
TAGS="$(gh api "repos/$REPO/releases?per_page=50" --jq '.[] | select(.draft == false) | .tag_name')"
TAG="$(printf '%s\n' "$TAGS" | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1 || true)"
[[ -n "$TAG" ]] || { echo "No valid release found" >&2; exit 1; }
VERSION="${TAG#v}"
CURRENT="$(readlink "$APP/current" 2>/dev/null || true)"
if [[ "$CURRENT" == "versions/$VERSION" && "${1:-}" != "--force" ]]; then
  echo "LBC user runtime already current: $VERSION"
  # Continue to repair the launcher and remove old user runtime copies.
  ALREADY_CURRENT=1
else
  ALREADY_CURRENT=0
fi
if [[ "$ALREADY_CURRENT" -eq 0 ]]; then
TMP="$(mktemp -d "$APP/update.XXXXXXXX")"
trap 'rm -rf "$TMP"' EXIT
DEB="linux-bridge-console_${VERSION}_all.deb"
gh release download "$TAG" --repo "$REPO" --dir "$TMP" --pattern "$DEB" --pattern "$DEB.sha256"
(cd "$TMP" && sha256sum -c "$DEB.sha256")
[[ "$(dpkg-deb -f "$TMP/$DEB" Package)" == "linux-bridge-console" ]] || exit 1
[[ "$(dpkg-deb -f "$TMP/$DEB" Version)" == "$VERSION" ]] || exit 1
[[ "$(dpkg-deb -f "$TMP/$DEB" Architecture)" == "all" ]] || exit 1
dpkg-deb -x "$TMP/$DEB" "$TMP/package"
python3 - "$TMP/package/usr/lib/linux-bridge-console" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
assert (root / "dashboard.py").is_file() and (root / "runner.py").is_file()
for py in root.glob("*.py"):
    compile(py.read_bytes(), str(py), "exec")
PY
DEST="$VERSIONS/$VERSION"
if [[ ! -d "$DEST" ]]; then
  mv "$TMP/package" "$DEST"
fi
ln -s "versions/$VERSION" "$APP/current.next"
mv -Tf "$APP/current.next" "$APP/current"
fi
# Installed package's wrapper remains available at /usr/bin/lbc.
# This user-level launcher always follows the newest verified runtime.
cat > "$BIN/lbc" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
APP="$HOME/.local/share/linux-bridge-console"
if [[ "${1:-}" == "update" ]]; then
  shift
  exec bash "$APP/current/usr/lib/linux-bridge-console/update-user.sh" "$@"
fi
exec python3 "$APP/current/usr/lib/linux-bridge-console/dashboard.py" "$@"
SH
chmod 0755 "$BIN/lbc.next"
mv -f "$BIN/lbc.next" "$BIN/lbc"
# Remove old user-runtime copies only after activating the verified version.
# Do not touch Debian-owned files, the GitHub job workspace, or user settings.
for old in "$VERSIONS"/*; do
  [[ -d "$old" && ! -L "$old" ]] || continue
  [[ "$old" == "$VERSIONS/$VERSION" ]] && continue
  [[ "$(basename "$old")" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || continue
  rm -rf -- "$old"
done
echo "LBC installed user runtime v$VERSION"
echo "Launcher: $BIN/lbc"
