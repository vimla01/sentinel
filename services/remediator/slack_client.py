import hashlib
import hmac
import time

import httpx

_REPLAY_WINDOW_SECONDS = 300


def verify_signature(signing_secret: str, timestamp: str, body: str, signature: str) -> bool:
    """Verifies Slack's request signature (see Slack's "Verifying requests
    from Slack" docs): HMAC-SHA256 over `v0:{timestamp}:{body}` keyed by the
    app's signing secret, with a 5-minute replay window on the timestamp."""
    if not signing_secret or not signature:
        return False
    try:
        request_time = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - request_time) > _REPLAY_WINDOW_SECONDS:
        return False
    basestring = f"v0:{timestamp}:{body}".encode()
    computed = "v0=" + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


class SlackClient:
    """Thin wrapper around Slack's Web API for the approval workflow: post a
    Block Kit message with Approve/Deny buttons, then update that same
    message in place once a human has responded via /slack/interactions."""

    def __init__(self, bot_token: str, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://slack.com",
            timeout=timeout,
            headers={"Authorization": f"Bearer {bot_token}"},
        )

    async def post_approval(self, channel: str, remediation_id: str, text: str) -> dict:
        return await self._call(
            "/api/chat.postMessage",
            {
                "channel": channel,
                "text": text,
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                    {
                        "type": "actions",
                        "block_id": "remediation_actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Approve"},
                                "style": "primary",
                                "action_id": "approve",
                                "value": remediation_id,
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Deny"},
                                "style": "danger",
                                "action_id": "deny",
                                "value": remediation_id,
                            },
                        ],
                    },
                ],
            },
        )

    async def update_message(self, channel: str, ts: str, text: str) -> dict:
        return await self._call(
            "/api/chat.update",
            {"channel": channel, "ts": ts, "text": text, "blocks": []},
        )

    async def _call(self, path: str, payload: dict) -> dict:
        response = await self._client.post(path, json=payload)
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"slack API error on {path}: {body.get('error')}")
        return body

    async def aclose(self) -> None:
        await self._client.aclose()
