import base64
import json
import unittest
from datetime import datetime, timezone

from src.ingestion.gmail_newsletter_fetcher import GmailNewsletterFetcher
from src.utils.source_labels import get_original_source_name


def _encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _message(message_id: str, subject: str, body: str, internal_date: datetime) -> dict:
    return {
        "id": message_id,
        "internalDate": str(int(internal_date.timestamp() * 1000)),
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": "Every <hello@every.to>"},
            ],
            "body": {"data": _encoded(body)},
        },
    }


class _Request:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def execute(self) -> dict:
        return self.payload


class _Messages:
    def __init__(self, messages: dict[str, dict]) -> None:
        self.messages = messages
        self.queries: list[str] = []

    def list(self, **kwargs) -> _Request:
        self.queries.append(kwargs["q"])
        return _Request({"messages": [{"id": message_id} for message_id in self.messages]})

    def get(self, **kwargs) -> _Request:
        return _Request(self.messages[kwargs["id"]])


class _Users:
    def __init__(self, messages: _Messages) -> None:
        self._messages = messages

    def messages(self) -> _Messages:
        return self._messages


class _Service:
    def __init__(self, messages: dict[str, dict]) -> None:
        self.messages_api = _Messages(messages)

    def users(self) -> _Users:
        return _Users(self.messages_api)


class GmailNewsletterFetcherTest(unittest.TestCase):
    def test_fetch_converts_message_to_content_item_and_decodes_every_url(self) -> None:
        every_payload = _encoded(
            json.dumps({"url": "https://every.to/vibe-check/opus-4-8-vibecheck"})
        )
        body = (
            "[Read the full Vibe Check]"
            f"(https://every.to/emails/click/token/{every_payload})\n\n"
            "Anthropic is back.\n\nWhat did you think of this post?\nBad"
        )
        service = _Service(
            {
                "msg-1": _message(
                    "msg-1",
                    "Vibe Check: Opus 4.8",
                    body,
                    datetime(2026, 5, 28, 17, 49, tzinfo=timezone.utc),
                )
            }
        )
        fetcher = GmailNewsletterFetcher(None, None, timeout_seconds=30, service=service)

        items = fetcher.fetch(
            [{"name": "every", "display_name": "Every", "query": "from:hello@every.to"}],
            seen_ids=set(),
            recent_days=1,
            start_at=datetime(2026, 5, 28, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 5, 29, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].content_id, "newsletter_email_msg-1")
        self.assertEqual(items[0].source_type, "newsletter_email")
        self.assertEqual(items[0].source_name, "every")
        self.assertEqual(get_original_source_name(items[0]), "Every")
        self.assertEqual(items[0].title, "Vibe Check: Opus 4.8")
        self.assertEqual(items[0].url, "https://every.to/vibe-check/opus-4-8-vibecheck")
        self.assertIn("Anthropic is back.", items[0].body)
        self.assertNotIn("What did you think", items[0].body)

    def test_fetch_uses_seen_ids_and_precise_window_boundaries(self) -> None:
        service = _Service(
            {
                "seen": _message("seen", "Seen", "Body", datetime(2026, 5, 28, 0, tzinfo=timezone.utc)),
                "start": _message("start", "Start", "Body", datetime(2026, 5, 28, 1, tzinfo=timezone.utc)),
                "end": _message("end", "End", "Body", datetime(2026, 5, 29, 1, tzinfo=timezone.utc)),
            }
        )
        fetcher = GmailNewsletterFetcher(None, None, timeout_seconds=30, service=service)

        items = fetcher.fetch(
            [{"name": "ai_valley", "display_name": "AI Valley", "query": "from:aivalley@mail.beehiiv.com"}],
            seen_ids={"newsletter_email_seen"},
            recent_days=1,
            start_at=datetime(2026, 5, 28, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 5, 29, 1, tzinfo=timezone.utc),
        )

        self.assertEqual([item.content_id for item in items], ["newsletter_email_start"])
        self.assertIn("after:2026/05/27", service.messages_api.queries[0])
        self.assertIn("before:2026/05/30", service.messages_api.queries[0])


if __name__ == "__main__":
    unittest.main()
