#!/usr/bin/env bash
set -euo pipefail

REPO="Pcattache30/Linux-Bridge-Console"
PACKAGE="linux-bridge-console"

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run as your normal user; sudo will be requested only for package installation." >&2
  exit 2
fi
for tool in gh dpkg dpkg-deb sha256sum sudo apt-get; do
  command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 2; }
done
gh auth status >/dev/null

CURRENT="$(dpkg-query -W -f='${Version}' "$PACKAGE")"
TAG="$(gh api "repos/$REPO/releases?per_page=30" --jq '[.[] | select(.draft == false) | .tag_name] | .[0]')"
if [[ ! "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "No valid published version found: $TAG" >&2
  exit 1
fi
VERSION="${TAG#v}"
if ! dpkg --compare-versions "$VERSION" gt "$CURRENT"; then
  echo "Linux Bridge Console is current: $CURRENT (latest release: $VERSION)"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
DEB="$PACKAGE"_"$VERSION"_all.deb
SUM="$DEB.sha256"
echo "Downloading verified release $TAG ..."
gh release download "$TAG" --repo "$REPO" --dir "$TMP" --pattern "$DEB" --pattern "$SUM"

if [[ ! -s "$TMP/$DEB" || ! -s "$TMP/$SUM" ]]; then
  echo "Release is missing the package or SHA-256 manifest; upgrade refused." >&2
  exit 1
fi
(cd "$TMP" && sha256sum -c "$SUM")
[[ "$(dpkg-deb -f "$TMP/$DEB" Package)" == "$PACKAGE" ]] || { echo "Package name mismatch" >&2; exit 1; }
[[ "$(dpkg-deb -f "$TMP/$DEB" Version)" == "$VERSION" ]] || { echo "Package version mismatch" >&2; exit 1; }
[[ "$(dpkg-deb -f "$TMP/$DEB" Architecture)" == "all" ]] || { echo "Unexpected package architecture" >&2; exit 1; }

echo "Installing $CURRENT -> $VERSION (sudo authentication may be requested)..."
sudo apt-get install -y "$TMP/$DEB"

if systemctl --user is-enabled --quiet linux-bridge-console.service 2>/dev/null; then
  systemctl --user restart linux-bridge-console.service
fi
echo "Updated to Linux Bridge Console $VERSION"
