import unittest
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from src.publishing.site_publisher import SitePublishResult, SitePublisher
from src.publishing.site_sync import sync_site_content
from src.pipeline import Pipeline


class SiteSyncTest(unittest.TestCase):
    def test_sync_site_content_writes_frontmatter_and_prunes_stale_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            site_root = root / "site"
            (project_root / "reports" / "daily").mkdir(parents=True)
            (project_root / "reports" / "weekly").mkdir(parents=True)
            (site_root / ".git").mkdir(parents=True)
            (site_root / "src" / "content" / "daily").mkdir(parents=True)
            (site_root / "src" / "content" / "weekly").mkdir(parents=True)

            (project_root / "reports" / "daily" / "2026-05-18.md").write_text(
                "# Daily title\n\nBody",
                encoding="utf-8",
            )
            (project_root / "reports" / "weekly" / "2026-W20.md").write_text(
                "# Weekly title\n\nBody",
                encoding="utf-8",
            )
            stale_path = site_root / "src" / "content" / "daily" / "stale.md"
            stale_path.write_text("old", encoding="utf-8")

            result = sync_site_content(project_root, site_root)

            daily_output = site_root / "src" / "content" / "daily" / "2026-05-18.md"
            weekly_output = site_root / "src" / "content" / "weekly" / "2026-w20.md"
            self.assertEqual(result.daily_count, 1)
            self.assertEqual(result.weekly_count, 1)
            self.assertTrue(daily_output.exists())
            self.assertTrue(weekly_output.exists())
            self.assertFalse(stale_path.exists())
            self.assertIn('routeSlug: "2026-05-18"', daily_output.read_text(encoding="utf-8"))
            self.assertIn('routeSlug: "2026-w20"', weekly_output.read_text(encoding="utf-8"))
            self.assertIn('updatedAt: "', daily_output.read_text(encoding="utf-8"))
            self.assertIn('updatedAt: "', weekly_output.read_text(encoding="utf-8"))


class SitePublisherTest(unittest.TestCase):
    @patch("src.publishing.site_publisher.sync_site_content")
    def test_publish_commits_only_when_changes_exist(self, sync_mock: Mock) -> None:
        sync_mock.return_value = Mock(daily_count=2, weekly_count=1)
        publisher = SitePublisher(Path("D:/project"), Path("D:/site"))
        publisher._validate_site_repo = Mock()  # type: ignore[method-assign]
        publisher._has_git_changes = Mock(return_value=True)  # type: ignore[method-assign]
        publisher._has_unpushed_commits = Mock(return_value=False)  # type: ignore[method-assign]
        publisher._run_git = Mock(return_value="")  # type: ignore[method-assign]

        result = publisher.publish("daily", target_label="2026-05-18")

        self.assertTrue(result.changed)
        self.assertEqual(result.commit_message, "publish: sync daily digest 2026-05-18")
        publisher._run_git.assert_any_call("add", ".")
        publisher._run_git.assert_any_call("commit", "-m", "publish: sync daily digest 2026-05-18")
        publisher._run_git.assert_any_call("push", "origin", "main")

    @patch("src.publishing.site_publisher.sync_site_content")
    @patch("src.publishing.site_publisher.time.sleep")
    def test_publish_retries_push_with_backoff_until_success(self, sleep_mock: Mock, sync_mock: Mock) -> None:
        sync_mock.return_value = Mock(daily_count=2, weekly_count=1)
        publisher = SitePublisher(
            Path("D:/project"),
            Path("D:/site"),
            push_retry_delays_seconds=(180, 300, 600),
        )
        publisher._validate_site_repo = Mock()  # type: ignore[method-assign]
        publisher._has_git_changes = Mock(return_value=True)  # type: ignore[method-assign]
        publisher._has_unpushed_commits = Mock(return_value=False)  # type: ignore[method-assign]
        push_error = subprocess.CalledProcessError(128, ["git", "push"], stderr="network down")
        publisher._run_git = Mock(side_effect=["", "", push_error, "", ""])  # type: ignore[method-assign]

        result = publisher.publish("daily", target_label="2026-05-18")

        self.assertTrue(result.changed)
        self.assertEqual(sleep_mock.call_args_list[0].args[0], 180)
        self.assertEqual(publisher._run_git.call_args_list[-1].args, ("push", "origin", "main"))

    @patch("src.publishing.site_publisher.sync_site_content")
    @patch("src.publishing.site_publisher.time.sleep")
    def test_publish_raises_after_all_push_retries_fail(self, sleep_mock: Mock, sync_mock: Mock) -> None:
        sync_mock.return_value = Mock(daily_count=2, weekly_count=1)
        publisher = SitePublisher(
            Path("D:/project"),
            Path("D:/site"),
            push_retry_delays_seconds=(180, 300, 600),
        )
        publisher._validate_site_repo = Mock()  # type: ignore[method-assign]
        publisher._has_git_changes = Mock(return_value=True)  # type: ignore[method-assign]
        publisher._has_unpushed_commits = Mock(return_value=False)  # type: ignore[method-assign]
        push_error = subprocess.CalledProcessError(128, ["git", "push"], stderr="auth failed")
        publisher._run_git = Mock(side_effect=["", "", push_error, push_error, push_error, push_error])  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "git push failed after 4 attempts: auth failed"):
            publisher.publish("daily", target_label="2026-05-18")

        self.assertEqual([call.args[0] for call in sleep_mock.call_args_list], [180, 300, 600])

    @patch("src.publishing.site_publisher.sync_site_content")
    @patch("src.publishing.site_publisher.time.sleep")
    def test_publish_retries_push_timeout_with_backoff_until_success(self, sleep_mock: Mock, sync_mock: Mock) -> None:
        sync_mock.return_value = Mock(daily_count=2, weekly_count=1)
        publisher = SitePublisher(
            Path("D:/project"),
            Path("D:/site"),
            push_retry_delays_seconds=(180, 300, 600),
        )
        publisher._validate_site_repo = Mock()  # type: ignore[method-assign]
        publisher._has_git_changes = Mock(return_value=True)  # type: ignore[method-assign]
        publisher._has_unpushed_commits = Mock(return_value=False)  # type: ignore[method-assign]
        push_timeout = subprocess.TimeoutExpired(["git", "push"], timeout=60)
        publisher._run_git = Mock(side_effect=["", "", push_timeout, ""])  # type: ignore[method-assign]

        result = publisher.publish("daily", target_label="2026-05-18")

        self.assertTrue(result.changed)
        self.assertEqual([call.args[0] for call in sleep_mock.call_args_list], [180])

    @patch("src.publishing.site_publisher.sync_site_content")
    @patch("src.publishing.site_publisher.time.sleep")
    def test_publish_raises_after_all_push_timeouts_fail(self, sleep_mock: Mock, sync_mock: Mock) -> None:
        sync_mock.return_value = Mock(daily_count=2, weekly_count=1)
        publisher = SitePublisher(
            Path("D:/project"),
            Path("D:/site"),
            push_retry_delays_seconds=(180, 300, 600),
        )
        publisher._validate_site_repo = Mock()  # type: ignore[method-assign]
        publisher._has_git_changes = Mock(return_value=True)  # type: ignore[method-assign]
        publisher._has_unpushed_commits = Mock(return_value=False)  # type: ignore[method-assign]
        push_timeout = subprocess.TimeoutExpired(["git", "push"], timeout=60)
        publisher._run_git = Mock(side_effect=["", "", push_timeout, push_timeout, push_timeout, push_timeout])  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "git push failed after 4 attempts: timed out after 60 seconds"):
            publisher.publish("daily", target_label="2026-05-18")

        self.assertEqual([call.args[0] for call in sleep_mock.call_args_list], [180, 300, 600])

    @patch("src.publishing.site_publisher.sync_site_content")
    def test_publish_pushes_unpushed_commits_even_without_new_file_changes(self, sync_mock: Mock) -> None:
        sync_mock.return_value = Mock(daily_count=2, weekly_count=1)
        publisher = SitePublisher(Path("D:/project"), Path("D:/site"))
        publisher._validate_site_repo = Mock()  # type: ignore[method-assign]
        publisher._has_git_changes = Mock(return_value=False)  # type: ignore[method-assign]
        publisher._has_unpushed_commits = Mock(return_value=True)  # type: ignore[method-assign]
        publisher._run_git = Mock(return_value="")  # type: ignore[method-assign]

        result = publisher.publish("daily", target_label="2026-05-18")

        self.assertFalse(result.changed)
        self.assertIsNone(result.commit_message)
        publisher._run_git.assert_called_once_with("push", "origin", "main")

    def test_recover_pending_push_pushes_unpushed_commits(self) -> None:
        publisher = SitePublisher(Path("D:/project"), Path("D:/site"))
        publisher._validate_site_repo = Mock()  # type: ignore[method-assign]
        publisher._has_unpushed_commits = Mock(return_value=True)  # type: ignore[method-assign]
        publisher._run_git = Mock(return_value="")  # type: ignore[method-assign]

        result = publisher.recover_pending_push()

        self.assertTrue(result.pushed)
        publisher._run_git.assert_called_once_with("push", "origin", "main")

    def test_recover_pending_push_skips_when_nothing_is_unpushed(self) -> None:
        publisher = SitePublisher(Path("D:/project"), Path("D:/site"))
        publisher._validate_site_repo = Mock()  # type: ignore[method-assign]
        publisher._has_unpushed_commits = Mock(return_value=False)  # type: ignore[method-assign]
        publisher._run_git = Mock(return_value="")  # type: ignore[method-assign]

        result = publisher.recover_pending_push()

        self.assertFalse(result.pushed)
        publisher._run_git.assert_not_called()


class PipelineSitePublishTest(unittest.TestCase):
    def test_daily_publish_error_does_not_break_digest(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.site_publisher = Mock()
        pipeline.site_publisher.publish.side_effect = RuntimeError("push failed")
        pipeline.state_manager = Mock()

        Pipeline._publish_site_report(pipeline, "daily", Path("reports/daily/2026-05-18.md"), "2026-05-18")

        pipeline.state_manager.write_heartbeat.assert_called_once()
        self.assertEqual(pipeline.state_manager.write_heartbeat.call_args.args[0], "site_publish_error")

    def test_publish_site_returns_disabled_when_not_configured(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.site_publisher = None

        payload = Pipeline.publish_site(pipeline)

        self.assertEqual(payload["enabled"], False)

    def test_publish_site_records_publish_result(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.site_publisher = Mock()
        pipeline.site_publisher.publish.return_value = SitePublishResult(
            synced=Mock(daily_count=20, weekly_count=3),
            changed=True,
            commit_message="publish: sync all digest all",
        )
        pipeline.state_manager = Mock()

        payload = Pipeline.publish_site(pipeline)

        self.assertTrue(payload["enabled"])
        self.assertTrue(payload["changed"])
        pipeline.state_manager.write_heartbeat.assert_called_once()

    def test_recover_site_publish_records_recovery_result(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.site_publisher = Mock()
        pipeline.site_publisher.recover_pending_push.return_value = Mock(pushed=True)
        pipeline.state_manager = Mock()

        payload = Pipeline.recover_site_publish(pipeline)

        self.assertTrue(payload["enabled"])
        self.assertTrue(payload["pushed"])
        pipeline.state_manager.write_heartbeat.assert_called_once_with(
            "site_publish_recovery",
            {"pushed": True},
        )

    def test_recover_site_publish_records_recovery_error(self) -> None:
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.site_publisher = Mock()
        pipeline.site_publisher.recover_pending_push.side_effect = RuntimeError("push failed")
        pipeline.state_manager = Mock()

        payload = Pipeline.recover_site_publish(pipeline)

        self.assertTrue(payload["enabled"])
        self.assertFalse(payload["pushed"])
        self.assertEqual(payload["error"], "push failed")
        pipeline.state_manager.write_heartbeat.assert_called_once_with(
            "site_publish_recovery_error",
            {"error": "push failed"},
        )
