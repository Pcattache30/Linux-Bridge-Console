#!/usr/bin/env bash
set -euo pipefail
echo LBC_FRESH_VM_007_START
echo "runner_host=$(hostname)"
echo "runner_user=$(id -un)"

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
if [[ ! -r "$HOME/.ssh/lbc_grid3_ed25519" ]]; then echo 'Missing configured SSH key' >&2; exit 10; fi
SSH_OPTS+=(-i "$HOME/.ssh/lbc_grid3_ed25519" -o IdentitiesOnly=yes)
if ! ssh "${SSH_OPTS[@]}" root@10.0.1.13 'command -v qm >/dev/null && test -f /var/lib/vz/template/iso/debian-auto.iso && pvesm status | grep -q "^TB7 " && echo GRID3_ACCESS_OK'; then
  echo "BLOCKED: The LBC VM cannot authenticate to GRID3 as root, or required storage/ISO unavailable."
  echo "No VM was created. Configure key-based SSH access for the LBC VM first."
  exit 10
fi

# Execute on GRID3. All changes below are confined to a new Proxmox VM.
ssh "${SSH_OPTS[@]}" root@10.0.1.13 'bash -se' <<'REMOTE'
set -euo pipefail
ID="$(pvesh get /cluster/nextid)"
NAME="LBC-PublicInstall-Test"
if qm list | grep -Fq "$NAME"; then
  echo "ERROR: test VM name already exists; refusing duplicate provision"
  exit 11
fi
echo "new_vmid=$ID"
echo "new_vm_name=$NAME"
qm create "$ID" --name "$NAME" --ostype l26 --cores 2 --sockets 1 --cpu host --memory 2048 \
  --net0 virtio,bridge=vmbr0 --scsihw virtio-scsi-single --scsi0 TB7:20 \
  --ide2 local:iso/debian-auto.iso,media=cdrom --boot 'order=scsi0;ide2' \
  --agent enabled=1 --onboot 0
qm start "$ID"
echo "VM_CREATED_AND_STARTED=$ID"
echo "Waiting for QEMU guest agent after automated Debian install..."
AGENT=0
for i in $(seq 1 100); do
  if qm agent "$ID" ping >/dev/null 2>&1; then
    AGENT=1
    break
  fi
  sleep 4
done
if [[ "$AGENT" != 1 ]]; then
  echo "VM_BOOTED_BUT_GUEST_AGENT_UNAVAILABLE; installation cannot be safely confirmed"
  exit 12
fi
echo "GUEST_AGENT_READY"

# Install the public release directly inside the Debian guest without a GitHub login.
INSTALL_SCRIPT="$(cat <<'GUEST'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 ca-certificates curl git gh bash util-linux
python3 - <<PY
import json, urllib.request, pathlib
api = "https://api.github.com/repos/Pcattache30/Linux-Bridge-Console/releases?per_page=40"
req = urllib.request.Request(api, headers={"User-Agent":"lbc-clean-install-test","Accept":"application/vnd.github+json"})
with urllib.request.urlopen(req, timeout=30) as f:
    releases = json.load(f)
def version(tag):
    import re
    m=re.fullmatch(r"v([0-9]+)\.([0-9]+)\.([0-9]+)",tag)
    return tuple(map(int,m.groups())) if m else (-1,-1,-1)
release=max((r for r in releases if not r["draft"] and version(r["tag_name"])[0] >= 0), key=lambda r:version(r["tag_name"]))
ver=release["tag_name"][1:]
name=f"linux-bridge-console_{ver}_all.deb"
assets={a["name"]:a["browser_download_url"] for a in release["assets"]}
for asset in (name,name+".sha256"):
    if asset not in assets:
        raise SystemExit("Missing published asset "+asset)
    req=urllib.request.Request(assets[asset],headers={"User-Agent":"lbc-clean-install-test"})
    with urllib.request.urlopen(req,timeout=60) as response:
        pathlib.Path("/tmp",asset).write_bytes(response.read())
print("RELEASE_VERSION="+ver)
PY
DEB="$(find /tmp -maxdepth 1 -name "linux-bridge-console_*_all.deb" | sort -V | tail -1)"
(cd /tmp && sha256sum -c "$(basename "$DEB").sha256")
apt-get install -y "$DEB"
echo "INSTALLED_VERSION=$(dpkg-query -W -f='${Version}' linux-bridge-console)"
test -x /usr/bin/lbc
echo "PUBLIC_GITHUB_INSTALL_SUCCESS"
GUEST
)"

# Run as guest root. Detect non-zero exit via the guest agent JSON.
OUT="$(qm guest exec "$ID" --timeout 300 --synchronous 1 -- bash -lc "$INSTALL_SCRIPT")"
echo "$OUT"
if ! printf '%s' "$OUT" | grep -Eq '"exitcode"[[:space:]]*:[[:space:]]*0'; then
  echo "Guest command exit code was not confirmed zero"
  exit 13
fi
qm set "$ID" --boot order=scsi0
echo "LBC_PUBLIC_VM_TEST_SUCCESS vmid=$ID"
REMOTE
echo LBC_FRESH_VM_007_COMPLETE
