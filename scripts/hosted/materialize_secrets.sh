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
"${python_exe}" -m src.hosting.secrets \
  --environment-variable AI_RADAR_STATE_SSH_KEY_B64 \
  --output "${runtime_dir}/state-sync-key"
"${python_exe}" -m src.hosting.secrets \
  --environment-variable AI_RADAR_STATE_KNOWN_HOSTS_B64 \
  --output "${runtime_dir}/known-hosts"

{
  echo "GMAIL_CREDENTIALS_PATH=${runtime_dir}/gmail-credentials.json"
  echo "GMAIL_TOKEN_PATH=${runtime_dir}/gmail-token.json"
  echo "AI_RADAR_STATE_SSH_KEY_PATH=${runtime_dir}/state-sync-key"
  echo "AI_RADAR_KNOWN_HOSTS_PATH=${runtime_dir}/known-hosts"
} >> "${GITHUB_ENV:?GITHUB_ENV is required}"
echo "materialized hosted credential files"
