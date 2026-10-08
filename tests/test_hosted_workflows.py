from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HostedWorkflowContractTest(unittest.TestCase):
    def test_smoke_is_manual_and_never_delivers_or_publishes(self) -> None:
        text = (ROOT / ".github" / "workflows" / "ai-radar-smoke.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("pull_request:", text)
        self.assertNotIn("schedule:", text)
        self.assertNotIn("--deliver", text)
        self.assertIn('SITE_PUBLISH_ENABLED: "false"', text)

    def test_daily_schedule_is_guarded_and_uses_pinned_actions(self) -> None:
        text = (ROOT / ".github" / "workflows" / "ai-radar-daily.yml").read_text(encoding="utf-8")

        self.assertIn("cron: '0 23 * * *'", text)
        self.assertIn("vars.AI_RADAR_PRODUCTION_ENABLED == 'true'", text)
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", text)
        self.assertIn("actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", text)
        self.assertIn("scripts/hosted/run_daily.sh", text)
        self.assertNotIn("pull_request:", text)

    def test_weekly_schedule_is_guarded_and_uses_delivery_guard(self) -> None:
        text = (ROOT / ".github" / "workflows" / "ai-radar-weekly.yml").read_text(encoding="utf-8")

        self.assertIn("cron: '0 1 * * 1'", text)
        self.assertIn("vars.AI_RADAR_PRODUCTION_ENABLED == 'true'", text)
        self.assertIn("scripts/hosted/run_delivery.sh weekly", text)
        self.assertNotIn("pull_request:", text)

    def test_workflows_do_not_upload_runtime_directories_as_artifacts(self) -> None:
        for path in (ROOT / ".github" / "workflows").glob("ai-radar-*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("actions/upload-artifact", text)
            self.assertNotIn("path: state", text)
            self.assertNotIn("path: transcripts", text)
            self.assertNotIn("path: reports", text)


if __name__ == "__main__":
    unittest.main()
