from __future__ import annotations

import logging
import time

import requests

LOGGER = logging.getLogger(__name__)


class FeishuDelivery:
    def __init__(
        self,
        webhook_url: str,
        timeout_seconds: int,
        max_retries: int = 3,
        retry_backoff_seconds: tuple[int, ...] = (30, 60, 120),
    ) -> None:
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    def send(self, payload: dict) -> dict:
        if not self.webhook_url:
            raise RuntimeError("FEISHU_WEBHOOK_URL is not configured")
        last_data: dict | None = None
        for attempt in range(1, self.max_retries + 1):
            response = requests.post(self.webhook_url, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            data = response.json()
            last_data = data
            LOGGER.info("Feishu delivery response: %s", data)
            if not self._is_rate_limited(data):
                return data

            if attempt == self.max_retries:
                break

            wait_seconds = self._retry_delay(attempt)
            LOGGER.warning(
                "Feishu delivery hit frequency limit on attempt %s/%s, retrying in %s seconds",
                attempt,
                self.max_retries,
                wait_seconds,
            )
            time.sleep(wait_seconds)

        raise RuntimeError(f"Feishu delivery failed after retries: {last_data}")

    def _is_rate_limited(self, data: dict) -> bool:
        code = int(data.get("code", data.get("StatusCode", 0)) or 0)
        message = str(data.get("msg", data.get("StatusMessage", ""))).lower()
        return code == 11232 or "frequency limited" in message

    def _retry_delay(self, attempt: int) -> int:
        index = min(attempt - 1, len(self.retry_backoff_seconds) - 1)
        return int(self.retry_backoff_seconds[index])
