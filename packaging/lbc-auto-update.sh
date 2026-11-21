#!/usr/bin/env bash
# Runs as root, from a root-owned Debian package. No user-supplied command arguments.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
CONFIG=/etc/linux-bridge-console/update-user
REPO=Pcattache30/Linux-Bridge-Console
PKG=linux-bridge-console
[[ -r "$CONFIG" ]] || { echo "Auto-update not configured."; exit 0; }
USER_NAME="$(cat "$CONFIG")"
[[ "$USER_NAME" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "Invalid update user" >&2; exit 1; }
USER_UID="$(id -u "$USER_NAME")"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
[[ -n "$USER_HOME" && -d "$USER_HOME" ]] || exit 1
GH_CONFIG_DIR="$USER_HOME/.config/gh"
[[ -f "$GH_CONFIG_DIR/hosts.yml" ]] || { echo "No GitHub authentication for $USER_NAME"; exit 1; }
user_gh() {
  runuser -u "$USER_NAME" -- env HOME="$USER_HOME" GH_CONFIG_DIR="$GH_CONFIG_DIR" gh "$@"
}
exec 9>/run/lock/linux-bridge-console-updater.lock
flock -n 9 || exit 0

CURRENT="$(dpkg-query -W -f='${Version}' "$PKG")"
RELEASES="$(user_gh api "repos/$REPO/releases?per_page=50" --jq '.[] | select(.draft == false) | .tag_name')"
TAG="$(printf '%s\n' "$RELEASES" | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1 || true)"
[[ -n "$TAG" ]] || { echo "No valid release"; exit 0; }
VERSION="${TAG#v}"
if ! dpkg --compare-versions "$VERSION" gt "$CURRENT"; then
  echo "Current version $CURRENT"
  exit 0
fi

# Worker holds the same advisory lock for the entire job. Never update mid-job.
STATE_DIR="$USER_HOME/.local/share/linux-bridge-console"
JOB_LOCK="$STATE_DIR/job.lock"
if [[ -f "$JOB_LOCK" ]]; then
  exec 8<"$JOB_LOCK"
  if ! flock -n -x 8; then
    echo "Job active; postponing update to $TAG"
    exit 0
  fi
fi
STATE="$STATE_DIR/worker-state.json"
if [[ -f "$STATE" ]] && grep -Eq '"phase": "(running-job|uploading)"' "$STATE"; then
  echo "Worker reports active job; postponing $TAG"
  exit 0
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
# Download as non-root and copy into root-owned staging before verifying.
USER_STAGE="$(runuser -u "$USER_NAME" -- mktemp -d)"
trap 'rm -rf "$STAGE"; rm -rf "$USER_STAGE"' EXIT
DEB="$PKG"_"$VERSION"_all.deb
SUM="$DEB.sha256"
runuser -u "$USER_NAME" -- env HOME="$USER_HOME" GH_CONFIG_DIR="$GH_CONFIG_DIR" gh release download "$TAG" --repo "$REPO" --dir "$USER_STAGE" --pattern "$DEB" --pattern "$SUM"
install -m 0600 "$USER_STAGE/$DEB" "$STAGE/$DEB"
install -m 0600 "$USER_STAGE/$SUM" "$STAGE/$SUM"
(cd "$STAGE" && sha256sum -c "$SUM")
[[ "$(dpkg-deb -f "$STAGE/$DEB" Package)" == "$PKG" ]] || exit 1
[[ "$(dpkg-deb -f "$STAGE/$DEB" Version)" == "$VERSION" ]] || exit 1
[[ "$(dpkg-deb -f "$STAGE/$DEB" Architecture)" == "all" ]] || exit 1

# The user service is not stopped unless a new verified package is ready.
echo "Applying LBC $CURRENT -> $VERSION"
apt-get install -y "$STAGE/$DEB"
# Reload the user's unit after package replacement. Restart only if running.
if [[ -d "/run/user/$USER_UID" ]]; then
  runuser -u "$USER_NAME" -- env XDG_RUNTIME_DIR="/run/user/$USER_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_UID/bus" \
    systemctl --user daemon-reload || true
  if runuser -u "$USER_NAME" -- env XDG_RUNTIME_DIR="/run/user/$USER_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_UID/bus" \
    systemctl --user is-active --quiet linux-bridge-console.service; then
    runuser -u "$USER_NAME" -- env XDG_RUNTIME_DIR="/run/user/$USER_UID" \
      DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_UID/bus" \
      systemctl --user restart linux-bridge-console.service
  fi
fi
echo "LBC updated to $VERSION"
