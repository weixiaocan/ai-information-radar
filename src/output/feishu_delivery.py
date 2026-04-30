from __future__ import annotations

import logging

import requests

LOGGER = logging.getLogger(__name__)


class FeishuDelivery:
    def __init__(self, webhook_url: str, timeout_seconds: int) -> None:
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds

    def send(self, payload: dict) -> dict:
        if not self.webhook_url:
            raise RuntimeError("FEISHU_WEBHOOK_URL is not configured")
        response = requests.post(self.webhook_url, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        data = response.json()
        LOGGER.info("Feishu delivery response: %s", data)
        return data

