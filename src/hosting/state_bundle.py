from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DURABLE_DIRECTORIES = ("state", "transcripts", "reports")
MANIFEST_FILENAME = ".ai-radar-manifest.json"
SCHEMA_VERSION = 1

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")
_FORBIDDEN_COMPONENTS = {".git", ".ssh", "secrets", "__pycache__"}
_FORBIDDEN_FILENAMES = {
    ".env",
    "credentials.json",
    "token.json",
    "known_hosts",
    "id_ed25519",
    "id_rsa",
}
_FORBIDDEN_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


class StateBundleError(ValueError):
    """Raised when a durable runtime bundle violates its contract."""


def build_manifest(
    root: Path,
    *,
    run_id: str,
    task: str,
    commit_sha: str,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    _validate_identifier("run_id", run_id)
    _validate_identifier("task", task)
    if not _COMMIT_PATTERN.fullmatch(commit_sha):
        raise StateBundleError("commit_sha must contain 7 to 40 hexadecimal characters")

    resolved_root = root.resolve()
    files, summary = _collect_bundle(resolved_root)
    bundle_sha256 = _hash_json(files)
    timestamp = created_at or datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "task": task,
        "commit_sha": commit_sha.lower(),
        "created_at": timestamp.astimezone(timezone.utc).isoformat(),
        "bundle_sha256": bundle_sha256,
        "summary": summary,
        "files": files,
    }


def write_manifest(
    root: Path,
    *,
    run_id: str,
    task: str,
    commit_sha: str,
    created_at: datetime | None = None,
) -> Path:
    manifest = build_manifest(
        root,
        run_id=run_id,
        task=task,
        commit_sha=commit_sha,
        created_at=created_at,
    )
    path = root.resolve() / MANIFEST_FILENAME
    _atomic_write_json(path, manifest)
    return path


def validate_manifest(root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    resolved_root = root.resolve()
    resolved_manifest = (manifest_path or (resolved_root / MANIFEST_FILENAME)).resolve()
    try:
        manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateBundleError("state bundle manifest is missing") from exc
    except json.JSONDecodeError as exc:
        raise StateBundleError("state bundle manifest is invalid JSON") from exc

    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise StateBundleError("unsupported state bundle manifest schema")
    files, summary = _collect_bundle(resolved_root)
    expected_hash = _hash_json(files)
    if (
        manifest.get("files") != files
        or manifest.get("summary") != summary
        or manifest.get("bundle_sha256") != expected_hash
    ):
        raise StateBundleError("state bundle manifest does not match durable files")
    return manifest


def prepare_snapshot(store_root: Path, *, run_id: str, allow_empty: bool = False) -> Path:
    _validate_identifier("run_id", run_id)
    root = store_root.resolve()
    incoming = root / "incoming"
    versions = root / "versions"
    staging = incoming / run_id
    incoming.mkdir(parents=True, exist_ok=True)
    versions.mkdir(parents=True, exist_ok=True)
    if staging.exists():
        raise StateBundleError("staging snapshot already exists")

    current = root / "current"
    if current.exists():
        shutil.copytree(current.resolve(), staging, copy_function=os.link)
    elif allow_empty:
        staging.mkdir()
        for directory in DURABLE_DIRECTORIES:
            (staging / directory).mkdir()
    else:
        raise StateBundleError("current snapshot is missing; explicit bootstrap is required")
    return staging


def promote_snapshot(store_root: Path, *, run_id: str) -> Path:
    _validate_identifier("run_id", run_id)
    root = store_root.resolve()
    staging = root / "incoming" / run_id
    destination = root / "versions" / run_id
    if staging.exists():
        staged_manifest = validate_manifest(staging)
        if destination.exists():
            current_manifest = validate_manifest(destination)
            if current_manifest["bundle_sha256"] != staged_manifest["bundle_sha256"]:
                raise StateBundleError("snapshot version already exists with different content")
            shutil.rmtree(staging)
        else:
            os.replace(staging, destination)
    elif destination.exists():
        validate_manifest(destination)
    else:
        raise StateBundleError("staging snapshot is missing")

    temporary_link = root / f".current-{run_id}"
    temporary_link.unlink(missing_ok=True)
    temporary_link.symlink_to(Path("versions") / run_id, target_is_directory=True)
    os.replace(temporary_link, root / "current")
    return destination


def prune_snapshots(store_root: Path, *, retain: int) -> list[str]:
    if retain < 1:
        raise StateBundleError("retain must be at least 1")
    root = store_root.resolve()
    versions = root / "versions"
    if not versions.exists():
        return []
    current_target = (root / "current").resolve() if (root / "current").exists() else None
    candidates = sorted(
        (path for path in versions.iterdir() if path.is_dir() and not path.name.startswith("pre-cutover")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed: list[str] = []
    for path in candidates[retain:]:
        if current_target is not None and path.resolve() == current_target:
            continue
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def _collect_bundle(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    files: list[dict[str, Any]] = []
    summary: dict[str, dict[str, int]] = {}
    for directory_name in DURABLE_DIRECTORIES:
        directory = root / directory_name
        if not directory.exists() or not directory.is_dir():
            raise StateBundleError(f"required durable directory is missing: {directory_name}")
        if directory.is_symlink():
            raise StateBundleError(f"symbolic link is not allowed: {directory_name}")
        file_count = 0
        byte_count = 0
        for path in sorted(directory.rglob("*"), key=lambda candidate: candidate.as_posix()):
            relative = path.relative_to(root)
            if relative.parts[:2] == ("state", "logs"):
                continue
            if path.is_symlink():
                raise StateBundleError(f"symbolic link is not allowed: {relative.as_posix()}")
            if not path.is_file():
                continue
            _reject_forbidden_file(relative)
            if directory_name == "state":
                _validate_state_file(path, relative)
            size = path.stat().st_size
            files.append(
                {
                    "path": relative.as_posix(),
                    "bytes": size,
                    "sha256": _hash_file(path),
                }
            )
            file_count += 1
            byte_count += size
        summary[directory_name] = {"files": file_count, "bytes": byte_count}
    return files, summary


def _reject_forbidden_file(relative: Path) -> None:
    lowered_parts = {part.lower() for part in relative.parts}
    name = relative.name.lower()
    if (
        lowered_parts.intersection(_FORBIDDEN_COMPONENTS)
        or name in _FORBIDDEN_FILENAMES
        or relative.suffix.lower() in _FORBIDDEN_SUFFIXES
    ):
        raise StateBundleError(f"forbidden runtime file: {relative.as_posix()}")


def _validate_state_file(path: Path, relative: Path) -> None:
    if path.suffix.lower() == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateBundleError(f"invalid JSON state file: {relative.as_posix()}") from exc
    elif path.suffix.lower() == ".jsonl" or path.name == "heartbeat.log":
        line_number = 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for line_number, line in enumerate(lines, start=1):
                if line.strip():
                    json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateBundleError(
                f"invalid JSONL state file: {relative.as_posix()} line {line_number}"
            ) from exc


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def _validate_identifier(label: str, value: str) -> None:
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise StateBundleError(f"{label} contains unsupported characters")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage durable AI Radar state bundles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--run-id", required=True)
    create.add_argument("--task", required=True)
    create.add_argument("--commit-sha", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--root", type=Path, required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--store-root", type=Path, required=True)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--allow-empty", action="store_true")

    promote = subparsers.add_parser("promote")
    promote.add_argument("--store-root", type=Path, required=True)
    promote.add_argument("--run-id", required=True)

    prune = subparsers.add_parser("prune")
    prune.add_argument("--store-root", type=Path, required=True)
    prune.add_argument("--retain", type=int, default=14)

    args = parser.parse_args()
    try:
        if args.command == "create":
            manifest_path = write_manifest(
                args.root,
                run_id=args.run_id,
                task=args.task,
                commit_sha=args.commit_sha,
            )
            print(manifest_path)
        elif args.command == "validate":
            manifest = validate_manifest(args.root)
            print(json.dumps({"run_id": manifest["run_id"], "bundle_sha256": manifest["bundle_sha256"]}))
        elif args.command == "prepare":
            print(prepare_snapshot(args.store_root, run_id=args.run_id, allow_empty=args.allow_empty))
        elif args.command == "promote":
            print(promote_snapshot(args.store_root, run_id=args.run_id))
        elif args.command == "prune":
            print(json.dumps({"removed": prune_snapshots(args.store_root, retain=args.retain)}))
    except StateBundleError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
