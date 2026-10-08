from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.hosting.delivery_receipt import (
    DeliveryReceiptConflict,
    complete_delivery,
    reserve_delivery,
    resolve_delivery_target,
)


class DeliveryReceiptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "state").mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_daily_target_comes_from_ingest_window(self) -> None:
        (self.root / "state" / "latest_ingest_window.json").write_text(
            json.dumps({"label_date": "2026-10-07"}),
            encoding="utf-8",
        )

        self.assertEqual("2026-10-07", resolve_delivery_target(self.root, "daily"))

    def test_weekly_target_is_previous_sunday_in_shanghai(self) -> None:
        now = datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertEqual("2026-10-11", resolve_delivery_target(self.root, "weekly", now=now))

    def test_completed_delivery_is_idempotently_skipped(self) -> None:
        result = reserve_delivery(
            self.root,
            task="daily",
            target="2026-10-07",
            run_id="run-1",
            commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        )
        self.assertEqual("reserved", result)
        complete_delivery(self.root, task="daily", target="2026-10-07", run_id="run-1")

        result = reserve_delivery(
            self.root,
            task="daily",
            target="2026-10-07",
            run_id="run-2",
            commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        )

        self.assertEqual("already_completed", result)

    def test_started_delivery_blocks_another_run(self) -> None:
        reserve_delivery(
            self.root,
            task="weekly",
            target="2026-10-11",
            run_id="run-1",
            commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        )

        with self.assertRaisesRegex(DeliveryReceiptConflict, "manual reconciliation"):
            reserve_delivery(
                self.root,
                task="weekly",
                target="2026-10-11",
                run_id="run-2",
                commit_sha="abcdef1234567890abcdef1234567890abcdef12",
            )

    def test_only_reserving_run_can_complete(self) -> None:
        reserve_delivery(
            self.root,
            task="daily",
            target="2026-10-07",
            run_id="run-1",
            commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        )

        with self.assertRaisesRegex(DeliveryReceiptConflict, "run_id"):
            complete_delivery(self.root, task="daily", target="2026-10-07", run_id="run-2")


if __name__ == "__main__":
    unittest.main()
