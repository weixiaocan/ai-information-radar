#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/common.sh"

run_id="${1:?usage: persist_state.sh RUN_ID TASK COMMIT_SHA}"
task="${2:?usage: persist_state.sh RUN_ID TASK COMMIT_SHA}"
commit_sha="${3:?usage: persist_state.sh RUN_ID TASK COMMIT_SHA}"
cd "${project_root}"
validate_state_environment
configure_ssh

"${python_exe}" -m src.hosting.state_bundle create \
  --root "${project_root}" \
  --run-id "${run_id}" \
  --task "${task}" \
  --commit-sha "${commit_sha}"

remote_tool_dir="${AI_RADAR_STATE_ROOT}/bin"
remote_tool="${remote_tool_dir}/state_bundle.py"
ssh "${ssh_options[@]}" "${ssh_target}" mkdir -p "${remote_tool_dir}"
rsync -a "${project_root}/src/hosting/state_bundle.py" "${ssh_target}:${remote_tool}"

prepare_args=(python3 "${remote_tool}" prepare --store-root "${AI_RADAR_STATE_ROOT}" --run-id "${run_id}")
if [[ "${AI_RADAR_ALLOW_EMPTY_BOOTSTRAP:-false}" == "true" ]]; then
  prepare_args+=(--allow-empty)
fi
ssh "${ssh_options[@]}" "${ssh_target}" "${prepare_args[@]}"

remote_staging="${AI_RADAR_STATE_ROOT}/incoming/${run_id}"
for directory in state transcripts reports; do
  rsync -a --delete \
    "${project_root}/${directory}/" \
    "${ssh_target}:${remote_staging}/${directory}/"
done
rsync -a \
  "${project_root}/.ai-radar-manifest.json" \
  "${ssh_target}:${remote_staging}/.ai-radar-manifest.json"

ssh "${ssh_options[@]}" "${ssh_target}" \
  python3 "${remote_tool}" promote --store-root "${AI_RADAR_STATE_ROOT}" --run-id "${run_id}"
ssh "${ssh_options[@]}" "${ssh_target}" \
  python3 "${remote_tool}" prune --store-root "${AI_RADAR_STATE_ROOT}" --retain "${AI_RADAR_STATE_RETAIN:-14}"
echo "persisted durable state for run=${run_id} task=${task}"
