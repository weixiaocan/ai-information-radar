from __future__ import annotations

import argparse
import os
import re
from collections.abc import Mapping


STATE_VARIABLES = (
    "AI_RADAR_STATE_HOST",
    "AI_RADAR_STATE_USER",
    "AI_RADAR_STATE_ROOT",
    "AI_RADAR_STATE_SSH_KEY_PATH",
    "AI_RADAR_KNOWN_HOSTS_PATH",
)
PROVIDER_VARIABLES = (
    "YOUTUBE_API_KEY",
    "DEEPSEEK_API_KEY",
    "SUPADATA_API_KEY",
    "GMAIL_CREDENTIALS_PATH",
    "GMAIL_TOKEN_PATH",
)
DELIVERY_VARIABLES = (
    "FEISHU_WEBHOOK_URL",
    "SITE_REPO_PATH",
)
PROFILE_VARIABLES = {
    "state": STATE_VARIABLES,
    "smoke": STATE_VARIABLES + PROVIDER_VARIABLES,
    "production": STATE_VARIABLES + PROVIDER_VARIABLES + DELIVERY_VARIABLES,
}

_HOST_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_USER_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_POSIX_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._/-]+$")


class EnvironmentValidationError(ValueError):
    """Raised when hosted configuration is missing or unsafe."""


def validate_hosted_environment(environment: Mapping[str, str], *, profile: str) -> None:
    required = PROFILE_VARIABLES.get(profile)
    if required is None:
        raise EnvironmentValidationError(f"unknown hosted environment profile: {profile}")

    missing = sorted(name for name in required if not str(environment.get(name, "")).strip())
    invalid: list[str] = []
    if not missing:
        if not _HOST_PATTERN.fullmatch(environment["AI_RADAR_STATE_HOST"].strip()):
            invalid.append("AI_RADAR_STATE_HOST")
        if not _USER_PATTERN.fullmatch(environment["AI_RADAR_STATE_USER"].strip()):
            invalid.append("AI_RADAR_STATE_USER")
        for name in (
            "AI_RADAR_STATE_ROOT",
            "AI_RADAR_STATE_SSH_KEY_PATH",
            "AI_RADAR_KNOWN_HOSTS_PATH",
        ):
            if not _is_safe_posix_path(environment[name].strip()):
                invalid.append(name)

    problems: list[str] = []
    if missing:
        problems.append("missing variables: " + ", ".join(missing))
    if invalid:
        problems.append("invalid variables: " + ", ".join(sorted(invalid)))
    if problems:
        raise EnvironmentValidationError("; ".join(problems))


def _is_safe_posix_path(value: str) -> bool:
    if not _POSIX_PATH_PATTERN.fullmatch(value) or "//" in value:
        return False
    return all(component not in {".", ".."} for component in value.split("/") if component)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AI Radar hosted environment variables")
    parser.add_argument("--profile", choices=sorted(PROFILE_VARIABLES), required=True)
    args = parser.parse_args()
    try:
        validate_hosted_environment(os.environ, profile=args.profile)
    except EnvironmentValidationError as exc:
        parser.error(str(exc))
    print(f"hosted environment profile '{args.profile}' is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
