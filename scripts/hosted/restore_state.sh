#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/common.sh"

run_id="${1:?usage: restore_state.sh RUN_ID}"
cd "${project_root}"
validate_state_environment
configure_ssh

remote_manifest="${AI_RADAR_STATE_ROOT}/current/.ai-radar-manifest.json"
if ! ssh "${ssh_options[@]}" "${ssh_target}" test -f "${remote_manifest}"; then
  if [[ "${AI_RADAR_ALLOW_EMPTY_BOOTSTRAP:-false}" == "true" ]]; then
    for directory in state transcripts reports; do
      mkdir -p "${project_root}/${directory}"
    done
    echo "state restore skipped for explicit empty bootstrap run=${run_id}"
    exit 0
  fi
  echo "current state snapshot is unavailable; refusing to run delivery" >&2
  exit 1
fi

for directory in state transcripts reports; do
  mkdir -p "${project_root}/${directory}"
  rsync -a --delete \
    "${ssh_target}:${AI_RADAR_STATE_ROOT}/current/${directory}/" \
    "${project_root}/${directory}/"
done
rsync -a \
  "${ssh_target}:${remote_manifest}" \
  "${project_root}/.ai-radar-manifest.json"

"${python_exe}" -m src.hosting.state_bundle validate --root "${project_root}"
echo "restored durable state for run=${run_id}"
