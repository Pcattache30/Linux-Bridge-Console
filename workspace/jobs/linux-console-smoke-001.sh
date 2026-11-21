#!/usr/bin/env bash
set -euo pipefail
printf 'LINUX_BRIDGE_SMOKE_001_START\n'
printf 'hostname=%s\n' "$(hostname)"
printf 'user=%s\n' "$(id -un)"
printf 'python=%s\n' "$(python3 --version)"
printf 'LINUX_BRIDGE_SMOKE_001_SUCCESS\n'
