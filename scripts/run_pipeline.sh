#!/usr/bin/env bash
set -euo pipefail

task="${1:?usage: run_pipeline.sh TASK [extra main.py arguments]}"
shift

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_exe="${AI_RADAR_PYTHON:-${project_root}/.venv/bin/python}"
logs_dir="${project_root}/state/logs"
timestamp="$(date +%Y%m%d-%H%M%S)"
log_path="${logs_dir}/${task}-${timestamp}.log"

mkdir -p "${logs_dir}"
cd "${project_root}"

exec > >(tee -a "${log_path}") 2>&1
echo "[$(date --iso-8601=seconds)] starting task=${task}"
"${python_exe}" main.py --task "${task}" "$@"
echo "[$(date --iso-8601=seconds)] completed task=${task}"
