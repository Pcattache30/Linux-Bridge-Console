#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-0.4.0}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Expected version MAJOR.MINOR.PATCH" >&2
  exit 2
fi
PKG="linux-bridge-console"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$OUT" "$STAGE/DEBIAN" \
  "$STAGE/usr/lib/linux-bridge-console" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/share/doc/$PKG" \
  "$STAGE/usr/lib/systemd/user"
cp "$ROOT/src/linux_bridge_console/"*.py "$STAGE/usr/lib/linux-bridge-console/"
install -m 0755 "$ROOT/packaging/lbc-packaged" "$STAGE/usr/bin/lbc"
install -m 0644 "$ROOT/packaging/linux-bridge-console.service" "$STAGE/usr/lib/systemd/user/linux-bridge-console.service"
install -m 0644 "$ROOT/README.md" "$STAGE/usr/share/doc/$PKG/README.md"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: Linux Bridge Console <noreply@localhost>
Depends: python3 (>= 3.11), git, gh, bash, util-linux
Description: Headless GitHub job worker with terminal dashboard
 Linux Bridge Console receives jobs from GitHub repositories, records job
 results and offers an interactive terminal dashboard.
 Automatic job execution is disabled by default.
EOF
python3 -m compileall -q "$STAGE/usr/lib/linux-bridge-console"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --info "$OUT/${PKG}_${VERSION}_all.deb"
sha256sum "$OUT/${PKG}_${VERSION}_all.deb"
echo "Package ready: $OUT/${PKG}_${VERSION}_all.deb"
