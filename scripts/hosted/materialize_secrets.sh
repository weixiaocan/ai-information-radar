#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/../.." && pwd)"
python_exe="${AI_RADAR_PYTHON:-python3}"
runtime_dir="${RUNNER_TEMP:?RUNNER_TEMP is required}/ai-radar-secrets"

mkdir -p "${runtime_dir}"
chmod 700 "${runtime_dir}"
cd "${project_root}"

"${python_exe}" -m src.hosting.secrets \
  --environment-variable GMAIL_CREDENTIALS_JSON_B64 \
  --output "${runtime_dir}/gmail-credentials.json"
"${python_exe}" -m src.hosting.secrets \
  --environment-variable GMAIL_TOKEN_JSON_B64 \
  --output "${runtime_dir}/gmail-token.json"

{
  echo "GMAIL_CREDENTIALS_PATH=${runtime_dir}/gmail-credentials.json"
  echo "GMAIL_TOKEN_PATH=${runtime_dir}/gmail-token.json"
} >> "${GITHUB_ENV:?GITHUB_ENV is required}"
echo "materialized hosted credential files"
