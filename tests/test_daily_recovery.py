from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.hosting.daily_recovery import DailyRecoveryError, validate_daily_recovery


class DailyRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        state = self.root / "state"
        state.mkdir()
        (self.root / ".ai-radar-manifest.json").write_text(
            json.dumps({"run_id": "daily-38665907190-1-failed", "task": "daily-failed"}),
            encoding="utf-8",
        )
        (state / "latest_ingest_window.json").write_text(
            json.dumps({"label_date": "2026-10-14"}), encoding="utf-8"
        )
        (state / "latest_ingest_ids.json").write_text(json.dumps(["item-1"]), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def validate(self) -> None:
        validate_daily_recovery(
            self.root,
            target="2026-10-14",
            source_run_id="daily-38665907190-1-failed",
        )

    def test_accepts_failed_snapshot_for_target_day(self) -> None:
        self.validate()

    def test_refuses_another_snapshot(self) -> None:
        with self.assertRaisesRegex(DailyRecoveryError, "expected failed daily run"):
            validate_daily_recovery(
                self.root, target="2026-10-14", source_run_id="daily-other-failed"
            )

    def test_refuses_wrong_target_day(self) -> None:
        with self.assertRaisesRegex(DailyRecoveryError, "ingest window"):
            validate_daily_recovery(
                self.root,
                target="2026-10-15",
                source_run_id="daily-38665907190-1-failed",
            )

    def test_refuses_any_existing_receipt(self) -> None:
        receipts = self.root / "state" / "delivery_receipts"
        receipts.mkdir()
        (receipts / "daily-2026-10-14.json").write_text(
            json.dumps({"status": "started"}), encoding="utf-8"
        )
        with self.assertRaisesRegex(DailyRecoveryError, "delivery receipt exists"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
