#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-0.4.0}"
PACKAGE="$ROOT/dist/linux-bridge-console_${VERSION}_all.deb"
if [[ ! -f "$PACKAGE" ]]; then
  echo "Build the package first: bash packaging/build-deb.sh $VERSION" >&2
  exit 1
fi
command -v gh >/dev/null
gh auth status >/dev/null
echo "Publishing $PACKAGE to GitHub release v$VERSION"
(cd "$ROOT/dist" && sha256sum "linux-bridge-console_${VERSION}_all.deb" > "linux-bridge-console_${VERSION}_all.deb.sha256")
gh release create "v$VERSION" "$PACKAGE" "$PACKAGE.sha256" \
  --repo Pcattache30/Linux-Bridge-Console \
  --title "Linux Bridge Console v$VERSION" \
  --notes "Early test release: curses dashboard, foreground Bash job runner, manual GitHub sync and opt-in user worker. Auto-run disabled. Worker credentials and multi-machine targeting are not production-ready." \
  --prerelease
