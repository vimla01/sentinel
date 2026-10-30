import hashlib
import hmac
import logging
import time

import httpx

_REPLAY_WINDOW_SECONDS = 300
logger = logging.getLogger("remediator.slack")


def verify_signature(
    signing_secret: str, timestamp: str, body: str, signature: str
) -> bool:
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
    computed = (
        "v0="
        + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(computed, signature)


class SlackClient:
    """Thin wrapper around Slack's Web API for the approval workflow: post a
    Block Kit message with Approve/Deny buttons, then update that same
    message in place once a human has responded via /slack/interactions."""

    def __init__(self, bot_token: str, timeout: float = 5.0) -> None:
        headers = {"Authorization": f"Bearer {bot_token}"} if bot_token else {}
        self._bot_token = bot_token
        self._client = httpx.AsyncClient(
            base_url="https://slack.com",
            timeout=timeout,
            headers=headers,
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

    async def join_channel(self, channel: str) -> dict:
        """Joins a public channel by name or ID via conversations.join, so the
        bot never needs a human to run `/invite @bot` after a fresh channel
        or workspace - requires the `channels:join` bot scope. Channel name
        (e.g. "#sentinel-incidents") must be resolved to an ID first, since
        conversations.join only accepts IDs."""
        if not channel:
            return {"ok": False, "skipped": True}
        channel_id = channel
        if channel.startswith("#"):
            channel_id = await self._resolve_channel_id(channel.lstrip("#"))
            if channel_id is None:
                logger.warning(
                    "could not resolve channel %s to an id; skipping auto-join",
                    channel,
                )
                return {"ok": False, "skipped": True}
        return await self._call("/api/conversations.join", {"channel": channel_id})

    async def _resolve_channel_id(self, channel_name: str) -> str | None:
        if not self._bot_token:
            return None
        cursor = ""
        while True:
            params = {"limit": 200, "types": "public_channel"}
            if cursor:
                params["cursor"] = cursor
            response = await self._client.get("/api/conversations.list", params=params)
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                return None
            for conv in body.get("channels", []):
                if conv.get("name") == channel_name:
                    return conv.get("id")
            cursor = body.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                return None

    async def post_message(
        self, channel: str, text: str, blocks: list | None = None
    ) -> dict:
        payload = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        return await self._call("/api/chat.postMessage", payload)

    async def _call(self, path: str, payload: dict) -> dict:
        if not self._bot_token:
            logger.debug("slack bot token not configured; skipping call to %s", path)
            return {"ok": False, "skipped": True}
        response = await self._client.post(path, json=payload)
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"slack API error on {path}: {body.get('error')}")
        return body

    async def aclose(self) -> None:
        await self._client.aclose()
