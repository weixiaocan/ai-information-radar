from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def build_smoke_summary(root: Path) -> dict[str, Any]:
    status_path = root / "state" / "latest_source_status.json"
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError("latest source status is unavailable after smoke ingest") from exc
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError("smoke ingest produced no classified source status")
    sources: list[dict[str, Any]] = []
    for source, status_payload in sorted(payload.items()):
        if not isinstance(status_payload, dict):
            raise RuntimeError(f"source status is invalid: {source}")
        status = str(status_payload.get("status", "")).strip()
        if not status:
            raise RuntimeError(f"source status is unclassified: {source}")
        sources.append(
            {
                "source": source,
                "status": status,
                "items": int(status_payload.get("items", status_payload.get("new_items", 0)) or 0),
            }
        )
    counts = Counter(entry["status"] for entry in sources)
    return {"source_count": len(sources), "status_counts": dict(sorted(counts.items())), "sources": sources}


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a sanitized AI Radar smoke summary")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()
    summary = build_smoke_summary(args.root)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.github_summary:
        lines = ["## AI Radar source smoke", "", f"Classified sources: {summary['source_count']}", "", "| Source | Status | Items |", "| --- | --- | ---: |"]
        lines.extend(f"| {entry['source']} | {entry['status']} | {entry['items']} |" for entry in summary["sources"])
        with args.github_summary.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
