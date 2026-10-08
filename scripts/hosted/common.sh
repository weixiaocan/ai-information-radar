#!/usr/bin/env bash
set -euo pipefail

hosted_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${hosted_script_dir}/../.." && pwd)"
python_exe="${AI_RADAR_PYTHON:-python3}"

require_tool() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "required tool is unavailable: $1" >&2
    return 1
  }
}

validate_state_environment() {
  "${python_exe}" -m src.hosting.environment --profile state
}

configure_ssh() {
  require_tool ssh
  require_tool rsync
  chmod 600 "${AI_RADAR_STATE_SSH_KEY_PATH}"
  chmod 600 "${AI_RADAR_KNOWN_HOSTS_PATH}"
  ssh_target="${AI_RADAR_STATE_USER}@${AI_RADAR_STATE_HOST}"
  ssh_options=(
    -i "${AI_RADAR_STATE_SSH_KEY_PATH}"
    -o BatchMode=yes
    -o IdentitiesOnly=yes
    -o StrictHostKeyChecking=yes
    -o "UserKnownHostsFile=${AI_RADAR_KNOWN_HOSTS_PATH}"
    -o ConnectTimeout=20
  )
  export RSYNC_RSH="ssh -i ${AI_RADAR_STATE_SSH_KEY_PATH} -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=${AI_RADAR_KNOWN_HOSTS_PATH} -o ConnectTimeout=20"
}
