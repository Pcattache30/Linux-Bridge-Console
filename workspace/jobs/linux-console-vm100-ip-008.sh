#!/usr/bin/env bash
set -euo pipefail
echo LBC_VM100_IP_CHECK_008_START
ssh -i "$HOME/.ssh/lbc_grid3_ed25519" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 root@10.0.1.13 'qm status 100; qm guest cmd 100 network-get-interfaces'
echo LBC_VM100_IP_CHECK_008_COMPLETE
