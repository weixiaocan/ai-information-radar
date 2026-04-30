import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.models.content_item import ContentItem
from src.storage.transcript_store import TranscriptStore


class TranscriptStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("transcripts") / "_test_store"
        shutil.rmtree(self.root, ignore_errors=True)
        self.store = TranscriptStore(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_save_uses_day_and_source_type_directories(self) -> None:
        item = ContentItem(
            content_id="youtube_abc",
            source_type="youtube",
            source_name="dwarkesh_patel",
            title="How GPT-5 Works",
            url="https://youtube.com/watch?v=abc",
            author="Dwarkesh Patel",
            published_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 4, 29, 1, tzinfo=timezone.utc),
            body="Description",
            body_type="description",
        )
        path = self.store.save(item)
        expected = self.root / "2026-04-29" / "youtube"
        self.assertEqual(path.parent, expected)
        self.assertTrue(path.name.startswith("dwarkesh_patel_"))


if __name__ == "__main__":
    unittest.main()
