from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from src.publishing.site_sync import SiteSyncResult, sync_site_content


@dataclass
class SitePublishResult:
    synced: SiteSyncResult
    changed: bool
    commit_message: str | None


class SitePublisher:
    def __init__(
        self,
        project_root: Path,
        site_repo_root: Path,
        git_branch: str = "main",
        timeout_seconds: int = 60,
        push_retry_delays_seconds: tuple[int, ...] = (180, 300, 600),
    ) -> None:
        self.project_root = project_root
        self.site_repo_root = site_repo_root
        self.git_branch = git_branch
        self.timeout_seconds = timeout_seconds
        self.push_retry_delays_seconds = push_retry_delays_seconds

    def publish(self, report_type: str, target_label: str | None = None) -> SitePublishResult:
        self._validate_site_repo()
        synced = sync_site_content(self.project_root, self.site_repo_root)
        if not self._has_git_changes():
            return SitePublishResult(synced=synced, changed=False, commit_message=None)

        commit_message = self._build_commit_message(report_type, target_label)
        self._run_git("add", ".")
        self._run_git("commit", "-m", commit_message)
        self._push_with_retries()
        return SitePublishResult(synced=synced, changed=True, commit_message=commit_message)

    def sync_only(self) -> SiteSyncResult:
        self._validate_site_repo()
        return sync_site_content(self.project_root, self.site_repo_root)

    def _validate_site_repo(self) -> None:
        if not self.site_repo_root.exists():
            raise FileNotFoundError(f"Site repo path does not exist: {self.site_repo_root}")
        if not (self.site_repo_root / ".git").exists():
            raise FileNotFoundError(f"Site repo path is not a git repository: {self.site_repo_root}")

    def _has_git_changes(self) -> bool:
        completed = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.site_repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout_seconds,
        )
        return bool((completed.stdout or "").strip())

    def _build_commit_message(self, report_type: str, target_label: str | None) -> str:
        label = (target_label or "content").strip()
        return f"publish: sync {report_type} digest {label}"

    def _push_with_retries(self) -> None:
        push_args = ("push", "origin", self.git_branch)
        last_error: subprocess.CalledProcessError | None = None
        total_attempts = len(self.push_retry_delays_seconds) + 1

        for attempt in range(1, total_attempts + 1):
            try:
                self._run_git(*push_args)
                return
            except subprocess.CalledProcessError as exc:
                last_error = exc
                if attempt >= total_attempts:
                    break
                time.sleep(self.push_retry_delays_seconds[attempt - 1])

        assert last_error is not None
        stderr = (last_error.stderr or "").strip()
        stdout = (last_error.stdout or "").strip()
        detail = stderr or stdout or str(last_error)
        raise RuntimeError(
            f"git push failed after {total_attempts} attempts: {detail}"
        ) from last_error

    def _run_git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.site_repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout_seconds,
        )
        return (completed.stdout or "") + (completed.stderr or "")
