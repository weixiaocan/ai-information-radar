from __future__ import annotations

import base64
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from src.models.content_item import ContentItem
from src.utils.time_utils import utc_days_ago, utc_now

LOGGER = logging.getLogger(__name__)

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class GmailNewsletterFetcher:
    def __init__(
        self,
        credentials_path: Path | None,
        token_path: Path | None,
        timeout_seconds: int,
        service: Any | None = None,
    ) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.timeout_seconds = timeout_seconds
        self.service = service

    def fetch(
        self,
        sources: list[dict[str, Any]],
        seen_ids: set[str],
        recent_days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[ContentItem]:
        enabled_sources = [source for source in sources if source.get("enabled", True)]
        if not enabled_sources:
            return []

        service = self.service or self._build_service()
        cutoff = start_at or utc_days_ago(recent_days)
        window_end = end_at or utc_now()
        results: list[ContentItem] = []
        for source in enabled_sources:
            query = self._build_query(source, cutoff, window_end)
            try:
                message_ids = self._list_message_ids(service, query)
            except Exception as exc:
                LOGGER.warning("Failed to search Gmail newsletter source %s: %s", source.get("name"), exc)
                continue
            for message_id in message_ids:
                content_id = f"newsletter_email_{message_id}"
                if content_id in seen_ids:
                    continue
                try:
                    message = self._get_message(service, message_id)
                    item = self._to_content_item(source, message, content_id)
                except Exception as exc:
                    LOGGER.warning("Failed to read Gmail newsletter message %s: %s", message_id, exc)
                    continue
                if item.published_at < cutoff or item.published_at >= window_end:
                    continue
                results.append(item)
        LOGGER.info("Fetched %s new Gmail newsletter items", len(results))
        return results

    def _build_service(self) -> Any:
        if self.credentials_path is None or self.token_path is None:
            raise ValueError("Gmail newsletter ingestion requires GMAIL_CREDENTIALS_PATH and GMAIL_TOKEN_PATH.")

        try:
            from google.auth.transport.requests import Request
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise RuntimeError("Install google-auth-oauthlib to enable Gmail newsletter ingestion.") from exc

        credentials = None
        if self.token_path.exists():
            credentials = Credentials.from_authorized_user_file(str(self.token_path), [GMAIL_READONLY_SCOPE])
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                if not self.credentials_path.exists():
                    raise FileNotFoundError(f"Gmail credentials file not found: {self.credentials_path}")
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), [GMAIL_READONLY_SCOPE])
                credentials = flow.run_local_server(port=0)
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        return _RequestsGmailService(AuthorizedSession(credentials), self.timeout_seconds)

    def _build_query(self, source: dict[str, Any], start_at: datetime, end_at: datetime) -> str:
        base_query = str(source.get("query", "")).strip()
        after_date = (start_at - timedelta(days=1)).date().strftime("%Y/%m/%d")
        before_date = (end_at + timedelta(days=1)).date().strftime("%Y/%m/%d")
        window_query = f"after:{after_date} before:{before_date} -in:trash -in:spam"
        return " ".join(part for part in [base_query, window_query] if part)

    def _list_message_ids(self, service: Any, query: str) -> list[str]:
        user_messages = service.users().messages()
        request = user_messages.list(userId="me", q=query, maxResults=100)
        message_ids: list[str] = []
        while request is not None:
            response = request.execute()
            message_ids.extend(str(message["id"]) for message in response.get("messages", []))
            page_token = response.get("nextPageToken")
            request = user_messages.list(userId="me", q=query, maxResults=100, pageToken=page_token) if page_token else None
        return message_ids

    def _get_message(self, service: Any, message_id: str) -> dict[str, Any]:
        return service.users().messages().get(userId="me", id=message_id, format="full").execute()

    def _to_content_item(self, source: dict[str, Any], message: dict[str, Any], content_id: str) -> ContentItem:
        headers = self._headers(message)
        message_id = str(message.get("id", "")).strip()
        body = self._clean_body(self._message_text(message.get("payload", {})))
        published_at = self._message_datetime(message)
        sender_name, sender_email = parseaddr(headers.get("from", ""))
        display_name = str(source.get("display_name", source.get("name", ""))).strip()
        return ContentItem(
            content_id=content_id,
            source_type="newsletter_email",
            source_name=str(source["name"]),
            title=headers.get("subject", "Untitled newsletter"),
            url=self._extract_primary_url(body, message_id),
            author=sender_name or sender_email or None,
            published_at=published_at,
            fetched_at=utc_now(),
            body=body,
            body_type="article",
            extra_metadata={
                "display_name": display_name,
                "gmail_message_id": message_id,
                "from": headers.get("from", ""),
                "newsletter_source": str(source["name"]),
            },
        )

    def _headers(self, message: dict[str, Any]) -> dict[str, str]:
        payload = message.get("payload", {})
        headers: dict[str, str] = {}
        for header in payload.get("headers", []):
            name = str(header.get("name", "")).lower()
            value = str(header.get("value", "")).strip()
            if name:
                headers[name] = value
        return headers

    def _message_datetime(self, message: dict[str, Any]) -> datetime:
        internal_date = str(message.get("internalDate", "")).strip()
        if internal_date:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
        return utc_now()

    def _message_text(self, payload: dict[str, Any]) -> str:
        text_parts: list[str] = []
        html_parts: list[str] = []
        self._collect_parts(payload, text_parts, html_parts)
        if text_parts:
            return "\n\n".join(part for part in text_parts if part.strip())
        return "\n\n".join(self._html_to_text(part) for part in html_parts if part.strip())

    def _collect_parts(self, payload: dict[str, Any], text_parts: list[str], html_parts: list[str]) -> None:
        mime_type = str(payload.get("mimeType", "")).lower()
        data = str(payload.get("body", {}).get("data", "")).strip()
        if data:
            decoded = self._decode_body(data)
            if mime_type == "text/plain":
                text_parts.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(decoded)
        for part in payload.get("parts", []):
            self._collect_parts(part, text_parts, html_parts)

    def _decode_body(self, data: str) -> str:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")

    def _html_to_text(self, value: str) -> str:
        value = re.sub(r"(?i)<br\s*/?>", "\n", value)
        value = re.sub(r"(?i)</p\s*>", "\n\n", value)
        value = re.sub(r"<[^>]+>", " ", value)
        return html.unescape(re.sub(r"[ \t]+", " ", value))

    def _clean_body(self, body: str) -> str:
        normalized = body.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        footer_patterns = [
            r"\nWhat did you think of this post\?.*\Z",
            r"\nHOW WAS TODAY'S NEWSLETTER.*\Z",
            r"\nUpdate your email preferences or unsubscribe.*\Z",
            r"\nYou received this email because.*\Z",
        ]
        for pattern in footer_patterns:
            normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE | re.DOTALL).strip()
        sponsor_patterns = [
            r"\n\[Want to sponsor Every\?.*?(?=\n\[Dan Shipper\]|\nTo read more essays|\Z)",
            r"\nREACH 100K\+ READERS.*\Z",
        ]
        for pattern in sponsor_patterns:
            normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE | re.DOTALL).strip()
        return normalized

    def _extract_primary_url(self, body: str, message_id: str) -> str:
        links = self._markdown_links(body)
        preferred_labels = ("read online", "read the full", "full vibe check", "vibe check")
        for label, url in links:
            if any(preferred in label.lower() for preferred in preferred_labels):
                return self._normalize_url(url)
        for _label, url in links:
            normalized = self._normalize_url(url)
            if normalized.startswith(("http://", "https://")):
                return normalized
        return f"https://mail.google.com/mail/#all/{message_id}" if message_id else ""

    def _markdown_links(self, body: str) -> list[tuple[str, str]]:
        return [
            (match.group("label").strip(), match.group("url").strip())
            for match in re.finditer(r"\[(?P<label>[^\]]+)\]\((?P<url>https?://[^)]+)\)", body)
        ]

    def _normalize_url(self, url: str) -> str:
        every_match = re.search(r"https://every\.to/emails/click/[^/\s)]+/(?P<payload>[A-Za-z0-9_\-=]+)", url)
        if every_match:
            decoded = self._decode_every_click_payload(every_match.group("payload"))
            if decoded:
                return decoded
        return url

    def _decode_every_click_payload(self, payload: str) -> str:
        try:
            padded = payload + "=" * (-len(payload) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        except Exception:
            return ""
        return str(data.get("url", "")).strip()


class _RequestsGmailService:
    def __init__(self, session: Any, timeout_seconds: int) -> None:
        self.session = session
        self.timeout_seconds = timeout_seconds

    def users(self) -> "_RequestsGmailUsers":
        return _RequestsGmailUsers(self.session, self.timeout_seconds)


class _RequestsGmailUsers:
    def __init__(self, session: Any, timeout_seconds: int) -> None:
        self.session = session
        self.timeout_seconds = timeout_seconds

    def messages(self) -> "_RequestsGmailMessages":
        return _RequestsGmailMessages(self.session, self.timeout_seconds)


class _RequestsGmailMessages:
    def __init__(self, session: Any, timeout_seconds: int) -> None:
        self.session = session
        self.timeout_seconds = timeout_seconds

    def list(self, **kwargs: Any) -> "_RequestsGmailRequest":
        user_id = kwargs.get("userId", "me")
        params = {
            "q": kwargs.get("q", ""),
            "maxResults": kwargs.get("maxResults", 100),
        }
        if kwargs.get("pageToken"):
            params["pageToken"] = kwargs["pageToken"]
        return _RequestsGmailRequest(
            self.session,
            f"https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages",
            self.timeout_seconds,
            params=params,
        )

    def get(self, **kwargs: Any) -> "_RequestsGmailRequest":
        user_id = kwargs.get("userId", "me")
        message_id = kwargs["id"]
        return _RequestsGmailRequest(
            self.session,
            f"https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages/{message_id}",
            self.timeout_seconds,
            params={"format": kwargs.get("format", "full")},
        )


class _RequestsGmailRequest:
    def __init__(
        self,
        session: Any,
        url: str,
        timeout_seconds: int,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.session = session
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.params = params or {}

    def execute(self) -> dict[str, Any]:
        response = self.session.get(self.url, params=self.params, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.json()
