#!/usr/bin/env bash
set -euo pipefail

task="${1:?usage: run_delivery.sh TASK RUN_ID COMMIT_SHA}"
run_id="${2:?usage: run_delivery.sh TASK RUN_ID COMMIT_SHA}"
commit_sha="${3:?usage: run_delivery.sh TASK RUN_ID COMMIT_SHA}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/../.." && pwd)"
python_exe="${AI_RADAR_PYTHON:-python3}"
cd "${project_root}"

target="$("${python_exe}" -m src.hosting.delivery_receipt target --root "${project_root}" --task "${task}")"
set +e
reserve_output="$("${python_exe}" -m src.hosting.delivery_receipt reserve --root "${project_root}" --task "${task}" --target "${target}" --run-id "${run_id}" --commit-sha "${commit_sha}" 2>&1)"
reserve_status=$?
set -e
if [[ ${reserve_status} -eq 20 ]]; then
  echo "delivery already completed task=${task} target=${target}; skipping"
  exit 0
fi
if [[ ${reserve_status} -ne 0 ]]; then
  echo "delivery reservation failed task=${task} target=${target}: ${reserve_output}" >&2
  exit "${reserve_status}"
fi

"${script_dir}/persist_state.sh" "${run_id}-reserved" "${task}-reserved" "${commit_sha}"

set +e
"${project_root}/scripts/run_pipeline.sh" "${task}" --deliver
pipeline_status=$?
set -e
if [[ ${pipeline_status} -eq 0 ]]; then
  "${python_exe}" -m src.hosting.delivery_receipt complete --root "${project_root}" --task "${task}" --target "${target}" --run-id "${run_id}"
else
  "${python_exe}" -m src.hosting.delivery_receipt uncertain --root "${project_root}" --task "${task}" --target "${target}" --run-id "${run_id}" --reason "pipeline_exit_${pipeline_status}"
fi
"${script_dir}/persist_state.sh" "${run_id}-final" "${task}-final" "${commit_sha}"
exit "${pipeline_status}"
