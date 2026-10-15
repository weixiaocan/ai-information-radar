from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from src.hosting.delivery_receipt import resolve_delivery_target


class DailyRecoveryError(ValueError):
    """The durable snapshot cannot safely resume a failed daily run."""


def validate_daily_recovery(root: Path, *, target: str, source_run_id: str) -> None:
    try:
        date.fromisoformat(target)
    except ValueError as exc:
        raise DailyRecoveryError("recovery target must be an ISO date") from exc

    manifest = _read_json(root / ".ai-radar-manifest.json")
    if manifest.get("run_id") != source_run_id or manifest.get("task") != "daily-failed":
        raise DailyRecoveryError("current snapshot is not the expected failed daily run")

    if resolve_delivery_target(root, "daily") != target:
        raise DailyRecoveryError("ingest window does not match the recovery target")

    ingest_ids = _read_json(root / "state" / "latest_ingest_ids.json")
    if not isinstance(ingest_ids, list) or not ingest_ids:
        raise DailyRecoveryError("failed snapshot has no ingested content to resume")

    receipt = root / "state" / "delivery_receipts" / f"daily-{target}.json"
    if receipt.exists():
        raise DailyRecoveryError("delivery receipt exists; reconcile delivery before recovery")


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise DailyRecoveryError(f"required recovery state is missing or invalid: {path.name}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a failed daily snapshot before resuming it")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--source-run-id", required=True)
    args = parser.parse_args()
    try:
        validate_daily_recovery(args.root, target=args.target, source_run_id=args.source_run_id)
    except DailyRecoveryError as exc:
        parser.error(str(exc))
    print(f"daily recovery validated target={args.target} source_run_id={args.source_run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
