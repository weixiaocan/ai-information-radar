from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.hosting.state_bundle import (
    MANIFEST_FILENAME,
    StateBundleError,
    build_manifest,
    validate_manifest,
    write_manifest,
)


class HostedStateBundleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self._write_fixture(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_manifest_round_trip_survives_fresh_workspace_copy(self) -> None:
        manifest_path = write_manifest(
            self.root,
            run_id="run-20261007-001",
            task="daily",
            commit_sha="1234567890abcdef1234567890abcdef12345678",
        )
        original = validate_manifest(self.root, manifest_path)

        restored_root = self.root.parent / f"{self.root.name}-restored"
        try:
            restored_root.mkdir()
            for directory in ("state", "transcripts", "reports"):
                shutil.copytree(self.root / directory, restored_root / directory)
            shutil.copy2(manifest_path, restored_root / MANIFEST_FILENAME)

            restored = validate_manifest(restored_root)
            self.assertEqual(original["bundle_sha256"], restored["bundle_sha256"])
            self.assertEqual(original["summary"], restored["summary"])
        finally:
            shutil.rmtree(restored_root, ignore_errors=True)

    def test_tampered_file_fails_validation(self) -> None:
        write_manifest(
            self.root,
            run_id="run-20261007-002",
            task="ingest",
            commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        )
        (self.root / "state" / "seen_ids.json").write_text('["changed"]', encoding="utf-8")

        with self.assertRaisesRegex(StateBundleError, "manifest does not match"):
            validate_manifest(self.root)

    def test_malformed_state_json_is_rejected(self) -> None:
        (self.root / "state" / "seen_ids.json").write_text("{broken", encoding="utf-8")

        with self.assertRaisesRegex(StateBundleError, "invalid JSON"):
            build_manifest(
                self.root,
                run_id="run-20261007-003",
                task="ingest",
                commit_sha="abcdef1234567890abcdef1234567890abcdef12",
            )

    def test_secret_like_file_is_rejected(self) -> None:
        (self.root / "state" / "credentials.json").write_text("{}", encoding="utf-8")

        with self.assertRaisesRegex(StateBundleError, "forbidden runtime file"):
            build_manifest(
                self.root,
                run_id="run-20261007-004",
                task="daily",
                commit_sha="abcdef1234567890abcdef1234567890abcdef12",
            )

    def test_runtime_logs_are_excluded_from_manifest(self) -> None:
        logs_dir = self.root / "state" / "logs"
        logs_dir.mkdir()
        (logs_dir / "ingest.log").write_text("provider response should not persist", encoding="utf-8")

        manifest = build_manifest(
            self.root,
            run_id="run-20261007-logs",
            task="ingest",
            commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        )

        paths = {entry["path"] for entry in manifest["files"]}
        self.assertNotIn("state/logs/ingest.log", paths)

    def test_non_utf8_state_file_is_rejected(self) -> None:
        (self.root / "state" / "seen_ids.json").write_bytes(b"\xff\xfe")

        with self.assertRaisesRegex(StateBundleError, "invalid JSON"):
            build_manifest(
                self.root,
                run_id="run-20261007-encoding",
                task="ingest",
                commit_sha="abcdef1234567890abcdef1234567890abcdef12",
            )

    def test_symlink_is_rejected(self) -> None:
        target = self.root / "outside.txt"
        target.write_text("outside", encoding="utf-8")
        link = self.root / "reports" / "linked.txt"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlink creation is unavailable on this host")

        with self.assertRaisesRegex(StateBundleError, "symbolic link"):
            build_manifest(
                self.root,
                run_id="run-20261007-005",
                task="daily",
                commit_sha="abcdef1234567890abcdef1234567890abcdef12",
            )

    def _write_fixture(self, root: Path) -> None:
        (root / "state").mkdir(parents=True)
        (root / "transcripts" / "2026-10-07" / "rss").mkdir(parents=True)
        (root / "reports" / "daily").mkdir(parents=True)
        (root / "state" / "seen_ids.json").write_text('["item-1"]', encoding="utf-8")
        (root / "state" / "source_health.jsonl").write_text(
            json.dumps({"timestamp": "2026-10-07T00:00:00+00:00", "status": "success"}) + "\n",
            encoding="utf-8",
        )
        (root / "state" / "heartbeat.log").write_text(
            json.dumps({"task": "ingest", "timestamp": "2026-10-07T00:00:00+00:00"}) + "\n",
            encoding="utf-8",
        )
        (root / "transcripts" / "2026-10-07" / "rss" / "item.md").write_text(
            "---\n{}\n---\n\nbody\n",
            encoding="utf-8",
        )
        (root / "reports" / "daily" / "2026-10-07.md").write_text("# Daily\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
