#!/usr/bin/env bash
set -euo pipefail

echo "LBC_UPDATE_002_START"
echo "hostname=$(hostname)"
echo "user=$(id -un)"
echo "current_version=$(dpkg-query -W -f='${Version}' linux-bridge-console)"
echo "Checking GitHub release..."
gh release view --repo Pcattache30/Linux-Bridge-Console --json tagName --jq '.tagName'

if ! sudo -n true >/dev/null 2>&1; then
    echo "LBC_UPDATE_002_NEEDS_SUDO"
    echo "Update not installed: this job cannot acquire sudo without a prompt."
    echo "Press U in the LBC dashboard to install the update interactively."
    exit 0
fi

echo "Sudo is already authorized; running LBC package updater..."
/usr/bin/lbc update
echo "installed_version=$(dpkg-query -W -f='${Version}' linux-bridge-console)"
echo "LBC_UPDATE_002_SUCCESS"
