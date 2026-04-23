"""Slack Incoming Webhook delivery adapter."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import SlackChannelConfig
from .messages import FunhouMessage
from .slack_formatter import build_slack_payload

DEFAULT_TIMEOUT_SEC = 5.0
MAX_ERROR_BODY_CHARS = 200


class SlackDeliveryError(Exception):
    """Raised when a Slack Incoming Webhook delivery attempt fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.original = original


def send_slack_message(
    message: FunhouMessage,
    config: SlackChannelConfig,
    *,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> None:
    """Send one funhou message to Slack using an Incoming Webhook."""

    if config.webhook is None:
        raise SlackDeliveryError("Slack webhook is not configured.")

    payload = build_slack_payload(
        message,
        mention_to=config.mention_to,
        mention_levels=set(config.mention_on),
    )
    _post_json(config.webhook, payload, timeout=timeout)


def _post_json(webhook: str, payload: dict[str, Any], *, timeout: float) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        webhook,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "funhou-hook",
        },
        method="POST",
    )

    try:
        with _open_request(request, timeout) as response:
            status_code = _get_status_code(response)
            response_body = _read_response_body(response)
    except HTTPError as exc:
        raise SlackDeliveryError(
            f"Slack webhook returned HTTP {exc.code}.",
            status_code=exc.code,
            response_body=_truncate_body(_decode_body(exc.read())),
            original=exc,
        ) from exc
    except (OSError, TimeoutError, URLError) as exc:
        raise SlackDeliveryError("Slack webhook request failed.", original=exc) from exc

    if not 200 <= status_code < 300:
        raise SlackDeliveryError(
            f"Slack webhook returned HTTP {status_code}.",
            status_code=status_code,
            response_body=response_body,
        )


def _open_request(request: Request, timeout: float) -> Any:
    return urlopen(request, timeout=timeout)


def _get_status_code(response: Any) -> int:
    status = getattr(response, "status", None)
    if status is not None:
        return int(status)
    return int(response.getcode())


def _read_response_body(response: Any) -> str:
    return _truncate_body(_decode_body(response.read()))


def _decode_body(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _truncate_body(body: str) -> str:
    return body[:MAX_ERROR_BODY_CHARS]
