#!/usr/bin/env bash
set -euo pipefail
echo "LBC_UPDATE_003_START"
echo "hostname=$(hostname)"
echo "user=$(id -un)"
echo "installed_before=$(dpkg-query -W -f='${Version}' linux-bridge-console)"

echo "Verifying prerelease v0.5.5 by explicit tag..."
gh api "repos/Pcattache30/Linux-Bridge-Console/releases/tags/v0.5.5" \
  --jq '{tag: .tag_name, prerelease: .prerelease, assets: [.assets[].name]}'

if ! sudo -n true 2>/dev/null; then
  echo "BLOCKED: Package installation requires sudo authentication."
  echo "No sudo privileges were changed and no update was installed."
  exit 3
fi

echo "Noninteractive sudo confirmed; invoking package updater..."
/usr/bin/lbc update

installed="$(dpkg-query -W -f='${Version}' linux-bridge-console)"
echo "installed_after=$installed"
if ! dpkg --compare-versions "$installed" ge 0.5.5; then
  echo "ERROR: Expected installed version >= 0.5.5."
  exit 4
fi
echo "LBC_UPDATE_003_SUCCESS"
