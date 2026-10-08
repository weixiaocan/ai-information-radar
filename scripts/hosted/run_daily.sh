#!/usr/bin/env bash
set -euo pipefail

run_id="${1:?usage: run_daily.sh RUN_ID COMMIT_SHA}"
commit_sha="${2:?usage: run_daily.sh RUN_ID COMMIT_SHA}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/../.." && pwd)"

run_stage() {
  local stage="$1"
  shift
  set +e
  bash "${project_root}/scripts/run_pipeline.sh" "${stage}" "$@"
  local status=$?
  set -e
  if [[ ${status} -ne 0 ]]; then
    bash "${script_dir}/persist_state.sh" "${run_id}-failed" "daily-failed" "${commit_sha}"
    exit "${status}"
  fi
}

run_stage ingest --days 1
run_stage tier1
run_stage daily-curate
bash "${script_dir}/run_delivery.sh" daily "${run_id}" "${commit_sha}"
