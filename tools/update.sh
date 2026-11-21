#!/usr/bin/env bash
# Safe updater for the source-based Linux Bridge Console development installation.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
BRANCH="main"
SERVICE="linux-bridge-console.service"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/linux-bridge-console-update-$(id -u).lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "Another LBC update is already running." >&2
  exit 1
fi
if [[ "$(git branch --show-current)" != "$BRANCH" ]]; then
  echo "Update refused: expected branch $BRANCH." >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "Update refused: local changes detected. Nothing modified." >&2
  exit 1
fi
BEFORE="$(git rev-parse HEAD)"
echo "Checking for updates to Linux Bridge Console..."
git fetch --quiet origin "$BRANCH"
AFTER="$(git rev-parse "origin/$BRANCH")"
if [[ "$BEFORE" == "$AFTER" ]]; then
  echo "Already current at ${BEFORE:0:12}."
  exit 0
fi
if ! git merge-base --is-ancestor "$BEFORE" "$AFTER"; then
  echo "Update refused: remote has diverged; no forced reset." >&2
  exit 1
fi
STAGE="$(mktemp -d)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT
git archive "$AFTER" | tar -x -C "$STAGE"
python3 -m compileall -q "$STAGE/src/linux_bridge_console"
bash -n "$STAGE/install-dev.sh" "$STAGE/tools/update.sh" "$STAGE/lbc"
WAS_RUNNING=false
if systemctl --user is-active --quiet "$SERVICE"; then
  WAS_RUNNING=true
  systemctl --user stop "$SERVICE"
fi
rollback() {
  echo "Update failed; rolling back to ${BEFORE:0:12}." >&2
  git reset --hard "$BEFORE" >/dev/null
  if [[ "$WAS_RUNNING" == true ]]; then
    systemctl --user restart "$SERVICE" || true
  fi
}
trap rollback ERR
git merge --ff-only "$AFTER" >/dev/null
if [[ "$WAS_RUNNING" == true ]]; then
  systemctl --user restart "$SERVICE"
  sleep 2
  systemctl --user is-active --quiet "$SERVICE"
fi
trap - ERR
echo "Updated from ${BEFORE:0:12} to ${AFTER:0:12}."
echo "Reopen lbc to use the updated dashboard."
