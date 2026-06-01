import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from src.models.content_item import ContentItem
from src.output.top_video_report import TopVideoReportWriter


class TopVideoReportWriterTest(unittest.TestCase):
    def test_writer_replaces_prompt_example_title_leak(self) -> None:
        client = Mock()
        client.ebook_report.return_value = "# AI 硬件浪潮才刚开始\n\nYC 正文内容"
        item = ContentItem(
            content_id="youtube_1",
            source_type="youtube",
            source_name="y_combinator",
            title="Inside YC&#39;s AI Playbook",
            url="https://youtube.com/watch?v=1",
            author="Y Combinator",
            published_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            body="Transcript",
            body_type="transcript",
            ai_score={"relevance": 9, "contrarian": 7, "guest_rarity": 6, "popularity": 5},
        )

        with TemporaryDirectory() as temp_dir:
            writer = TopVideoReportWriter(client, Path("prompts/ebook_report.md"), Path(temp_dir))
            paths = writer.write([item])
            report_text = paths[0].read_text(encoding="utf-8")

        self.assertTrue(report_text.startswith("# YC AI Playbook 内幕"))
        self.assertIn("YC 正文内容", report_text)


if __name__ == "__main__":
    unittest.main()
