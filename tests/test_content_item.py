import unittest
from datetime import datetime, timezone

from src.models.content_item import ContentItem


class ContentItemTest(unittest.TestCase):
    def test_round_trip(self) -> None:
        item = ContentItem(
            content_id="youtube_123",
            source_type="youtube",
            source_name="latent_space",
            title="Test",
            url="https://example.com",
            author="Author",
            published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 4, 28, 1, tzinfo=timezone.utc),
            body="hello",
            body_type="transcript",
        )
        payload = item.to_dict()
        reconstructed = ContentItem.from_dict(payload)
        self.assertEqual(reconstructed.content_id, item.content_id)
        self.assertEqual(reconstructed.published_at, item.published_at)


if __name__ == "__main__":
    unittest.main()
