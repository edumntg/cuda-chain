"""Webhook notifications. Each webhook gets a JSON POST; Slack-style hooks get {"text"}."""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from .config import WebhookConfig

log = logging.getLogger("plasmon.notify")


class Notifier:
    def __init__(self, hooks: list[WebhookConfig], public_url: str = ""):
        self.hooks = hooks
        self.public_url = public_url

    def send(self, event: str, text: str, data: dict[str, Any]) -> None:
        for hook in self.hooks:
            if hook.events and event not in hook.events:
                continue
            payload = {"text": text} if hook.format == "slack" else {"event": event, "text": text, "data": data, "server": self.public_url}
            threading.Thread(target=self._post, args=(hook.url, payload), daemon=True).start()

    @staticmethod
    def _post(url: str, payload: dict[str, Any]) -> None:
        try:
            httpx.post(url, json=payload, timeout=10)
        except Exception as e:  # a dead webhook must not affect the round
            log.warning("webhook %s failed: %s", url, e)
