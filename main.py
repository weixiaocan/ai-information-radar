from __future__ import annotations

import argparse
import json
import sys

from src.pipeline import Pipeline
from src.utils.config import load_settings
from src.utils.logging_utils import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Radar pipeline runner")
    parser.add_argument(
        "--task",
        required=True,
        choices=["ingest", "tier1", "tier2", "daily-curate", "daily", "weekly", "all"],
        help="Task to run",
    )
    parser.add_argument(
        "--deliver",
        action="store_true",
        help="Send generated digest to Feishu for daily or weekly tasks",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Override the ingest lookback window in days",
    )
    parser.add_argument(
        "--ignore-seen",
        action="store_true",
        help="Ignore seen_ids during ingest so historical windows can be replayed",
    )
    return parser.parse_args()


def main() -> None:
    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    settings = load_settings()
    pipeline = Pipeline(settings)

    items = []
    if args.task in {"ingest", "all"}:
        items = pipeline.ingest(recent_days_override=args.days, ignore_seen=args.ignore_seen)

    if args.task in {"tier1", "all"}:
        items = pipeline.tier1(items)

    if args.task == "daily-curate":
        payload = pipeline.daily_curate()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.task == "all":
        pipeline.daily_curate(items)

    if args.task == "daily":
        payload = pipeline.daily(deliver=args.deliver)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.task == "all":
        payload = pipeline.daily(items, deliver=args.deliver)
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.task in {"tier2", "all"}:
        items = pipeline.tier2(items)

    if args.task == "weekly":
        payload = pipeline.weekly(deliver=args.deliver)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.task == "all":
        payload = pipeline.weekly(items, deliver=args.deliver)
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
