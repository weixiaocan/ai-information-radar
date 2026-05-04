import unittest
from datetime import datetime, timezone

from src.models.content_item import ContentItem
from src.utils.source_labels import get_original_source_name, resolve_zara_source_name


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

    def test_original_source_name_prefers_builder_name_for_zara_x(self) -> None:
        item = ContentItem(
            content_id="zara_x_123",
            source_type="zara_x",
            source_name="zara_x",
            title="Test",
            url="https://x.com/test/status/1",
            author="Aaron Levie",
            published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 4, 28, 1, tzinfo=timezone.utc),
            body="hello",
            body_type="summary",
            extra_metadata={"raw_entry": {"author": "Aaron Levie"}},
        )
        self.assertEqual(get_original_source_name(item), "Aaron Levie")

    def test_original_source_name_prefers_raw_name_for_historical_zara_blog(self) -> None:
        item = ContentItem(
            content_id="zara_blog_123",
            source_type="zara_blog",
            source_name="zara_blog",
            title="Test",
            url="https://example.com/post",
            author=None,
            published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 4, 28, 1, tzinfo=timezone.utc),
            body="hello",
            body_type="article",
            extra_metadata={"raw_entry": {"name": "Anthropic Engineering"}},
        )
        self.assertEqual(get_original_source_name(item), "Anthropic Engineering")

    def test_resolve_zara_source_name_uses_entry_origin(self) -> None:
        self.assertEqual(resolve_zara_source_name("zara_x", {"author": "Peter Yang"}), "Peter Yang")
        self.assertEqual(
            resolve_zara_source_name("zara_podcast", {"name": "Training Data"}),
            "Training Data",
        )


if __name__ == "__main__":
    unittest.main()
