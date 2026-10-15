import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from src.pipeline import Pipeline

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _shanghai(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SHANGHAI)


def _pipeline() -> Pipeline:
    pipeline = Pipeline.__new__(Pipeline)
    pipeline.state_manager = Mock()
    pipeline.settings = Mock(
        daily_window_hour=7,
        ingest_max_catchup_days=3,
        bootstrap_days=7,
    )
    return pipeline


class FixedIngestWindowTest(unittest.TestCase):
    def _resolve(self, pipeline: Pipeline, now: datetime, previous_end: datetime | None, seen=frozenset({"x"})):
        previous_window = {"end_at": previous_end.isoformat()} if previous_end else {}
        return Pipeline._resolve_ingest_window(
            pipeline,
            previous_window,
            now=now,
            recent_days=1,
            recent_days_override=None,
            seen_ids=set(seen),
        )

    def test_window_is_fixed_regardless_of_trigger_time(self) -> None:
        pipeline = _pipeline()
        previous_end = _shanghai(2026, 10, 14, 7)
        expected = (_shanghai(2026, 10, 14, 7), _shanghai(2026, 10, 15, 7), "2026-10-14")

        for run_at in (_shanghai(2026, 10, 15, 7, 1), _shanghai(2026, 10, 15, 9, 30), _shanghai(2026, 10, 15, 11, 34)):
            with self.subTest(run_at=run_at):
                start, end, label = self._resolve(pipeline, run_at, previous_end)
                self.assertEqual((start, end, label), expected)

    def test_late_previous_run_overlaps_instead_of_leaving_gap(self) -> None:
        pipeline = _pipeline()
        # Legacy rolling window ended at the late trigger time.
        previous_end = _shanghai(2026, 10, 15, 9, 29)

        start, end, label = self._resolve(pipeline, _shanghai(2026, 10, 16, 10, 0), previous_end)

        self.assertEqual(start, _shanghai(2026, 10, 15, 7))
        self.assertEqual(end, _shanghai(2026, 10, 16, 7))
        self.assertEqual(label, "2026-10-15")

    def test_missed_day_is_caught_up(self) -> None:
        pipeline = _pipeline()

        start, end, label = self._resolve(pipeline, _shanghai(2026, 10, 16, 9, 0), _shanghai(2026, 10, 14, 7))

        self.assertEqual(start, _shanghai(2026, 10, 14, 7))
        self.assertEqual(end, _shanghai(2026, 10, 16, 7))
        self.assertEqual(label, "2026-10-15")
        pipeline.state_manager.append_ops_event.assert_not_called()

    def test_catch_up_is_capped_and_reported(self) -> None:
        pipeline = _pipeline()

        start, end, _ = self._resolve(pipeline, _shanghai(2026, 10, 20, 9, 0), _shanghai(2026, 10, 10, 7))

        self.assertEqual(start, end - timedelta(days=3))
        event = pipeline.state_manager.append_ops_event.call_args.args[0]
        self.assertEqual(event["event"], "ingest_catchup_truncated")

    def test_run_before_boundary_uses_previous_window(self) -> None:
        pipeline = _pipeline()

        start, end, label = self._resolve(pipeline, _shanghai(2026, 10, 15, 6, 30), _shanghai(2026, 10, 14, 7))

        self.assertEqual(end, _shanghai(2026, 10, 14, 7))
        self.assertEqual(start, _shanghai(2026, 10, 13, 7))
        self.assertEqual(label, "2026-10-13")

    def test_bootstrap_uses_bootstrap_days_ending_at_boundary(self) -> None:
        pipeline = _pipeline()

        start, end, _ = self._resolve(pipeline, _shanghai(2026, 10, 15, 9, 0), None, seen=frozenset())

        self.assertEqual(end, _shanghai(2026, 10, 15, 7))
        self.assertEqual(start, end - timedelta(days=7))

    def test_explicit_days_override_keeps_rolling_window(self) -> None:
        pipeline = _pipeline()
        now = datetime(2026, 10, 15, 2, 30, tzinfo=timezone.utc)

        start, end, label = Pipeline._resolve_ingest_window(
            pipeline,
            {"end_at": _shanghai(2026, 10, 14, 7).isoformat()},
            now=now,
            recent_days=2,
            recent_days_override=2,
            seen_ids={"x"},
        )

        self.assertEqual((start, end, label), (now - timedelta(days=2), now, None))


if __name__ == "__main__":
    unittest.main()
