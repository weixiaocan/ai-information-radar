from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.utils.atomic_file import atomic_write_text
from src.utils.time_utils import utc_now


ALREADY_COMPLETED_EXIT_CODE = 20
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
_TASKS = {"daily", "weekly"}
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")


class DeliveryReceiptConflict(RuntimeError):
    """Raised when delivery may already have happened and needs reconciliation."""


def resolve_delivery_target(root: Path, task: str, *, now: datetime | None = None) -> str:
    _validate_task(task)
    if task == "daily":
        path = root / "state" / "latest_ingest_window.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise DeliveryReceiptConflict("daily ingest window is unavailable") from exc
        target = str(payload.get("label_date", "")).strip()
        _validate_target(target)
        return target

    local_now = (now or datetime.now(LOCAL_TIMEZONE)).astimezone(LOCAL_TIMEZONE)
    target_date = local_now.date() - timedelta(days=local_now.date().weekday() + 1)
    return target_date.isoformat()


def reserve_delivery(
    root: Path,
    *,
    task: str,
    target: str,
    run_id: str,
    commit_sha: str,
) -> str:
    path = _receipt_path(root, task, target)
    _validate_run_id(run_id)
    if not _COMMIT_PATTERN.fullmatch(commit_sha):
        raise DeliveryReceiptConflict("commit_sha is invalid")
    existing = _load_receipt(path)
    if existing:
        if existing.get("status") == "completed":
            return "already_completed"
        raise DeliveryReceiptConflict(
            f"delivery receipt is {existing.get('status', 'unknown')}; manual reconciliation is required"
        )
    _write_receipt(
        path,
        {
            "schema_version": 1,
            "task": task,
            "target": target,
            "run_id": run_id,
            "commit_sha": commit_sha.lower(),
            "status": "started",
            "started_at": utc_now().isoformat(),
        },
    )
    return "reserved"


def complete_delivery(root: Path, *, task: str, target: str, run_id: str) -> None:
    _transition(root, task=task, target=target, run_id=run_id, status="completed")


def mark_delivery_uncertain(root: Path, *, task: str, target: str, run_id: str, reason: str) -> None:
    _transition(root, task=task, target=target, run_id=run_id, status="uncertain", reason=reason)


def _transition(
    root: Path,
    *,
    task: str,
    target: str,
    run_id: str,
    status: str,
    reason: str = "",
) -> None:
    path = _receipt_path(root, task, target)
    existing = _load_receipt(path)
    if not existing or existing.get("status") != "started":
        raise DeliveryReceiptConflict("delivery receipt is not in started state")
    if existing.get("run_id") != run_id:
        raise DeliveryReceiptConflict("delivery receipt run_id does not match")
    payload = dict(existing)
    payload["status"] = status
    payload["updated_at"] = utc_now().isoformat()
    if reason:
        payload["reason"] = reason
    _write_receipt(path, payload)


def _receipt_path(root: Path, task: str, target: str) -> Path:
    _validate_task(task)
    _validate_target(target)
    return root / "state" / "delivery_receipts" / f"{task}-{target}.json"


def _load_receipt(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DeliveryReceiptConflict("delivery receipt is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise DeliveryReceiptConflict("delivery receipt has an invalid shape")
    return payload


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_task(task: str) -> None:
    if task not in _TASKS:
        raise DeliveryReceiptConflict("delivery task must be daily or weekly")


def _validate_target(target: str) -> None:
    if not _DATE_PATTERN.fullmatch(target):
        raise DeliveryReceiptConflict("delivery target must be an ISO date")
    try:
        datetime.fromisoformat(target)
    except ValueError as exc:
        raise DeliveryReceiptConflict("delivery target is not a valid date") from exc


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise DeliveryReceiptConflict("delivery run_id is invalid")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage durable AI Radar delivery receipts")
    parser.add_argument("command", choices=("target", "reserve", "complete", "uncertain"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--task", choices=sorted(_TASKS), required=True)
    parser.add_argument("--target")
    parser.add_argument("--run-id")
    parser.add_argument("--commit-sha")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    try:
        target = args.target or resolve_delivery_target(args.root, args.task)
        if args.command == "target":
            print(target)
            return 0
        if not args.run_id:
            raise DeliveryReceiptConflict("run_id is required")
        if args.command == "reserve":
            if not args.commit_sha:
                raise DeliveryReceiptConflict("commit_sha is required")
            result = reserve_delivery(
                args.root,
                task=args.task,
                target=target,
                run_id=args.run_id,
                commit_sha=args.commit_sha,
            )
            print(result)
            return ALREADY_COMPLETED_EXIT_CODE if result == "already_completed" else 0
        if args.command == "complete":
            complete_delivery(args.root, task=args.task, target=target, run_id=args.run_id)
            print("completed")
            return 0
        mark_delivery_uncertain(
            args.root,
            task=args.task,
            target=target,
            run_id=args.run_id,
            reason=args.reason or "pipeline_failed",
        )
        print("uncertain")
        return 0
    except DeliveryReceiptConflict as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
