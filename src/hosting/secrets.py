from __future__ import annotations

import argparse
import base64
import binascii
import os
import tempfile
from pathlib import Path


class SecretMaterializationError(ValueError):
    """Raised when a hosted secret cannot be materialized safely."""


def materialize_secret_file(encoded_value: str, destination: Path, *, label: str) -> Path:
    if not encoded_value:
        raise SecretMaterializationError(f"{label} is empty")
    try:
        payload = base64.b64decode(encoded_value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretMaterializationError(f"{label} is not valid base64") from exc
    if not payload:
        raise SecretMaterializationError(f"{label} decoded to an empty file")

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.is_symlink():
        raise SecretMaterializationError(f"{label} destination must not be a symbolic link")

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        os.chmod(destination, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize one base64 AI Radar secret file")
    parser.add_argument("--environment-variable", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    label = args.environment_variable
    try:
        materialize_secret_file(os.environ.get(label, ""), args.output, label=label)
    except SecretMaterializationError as exc:
        parser.error(str(exc))
    print(f"materialized {label} at the configured temporary path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
