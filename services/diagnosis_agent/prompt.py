import json
import re

from .runbooks import Runbook

# Sent as the chat "system" turn (see ollama_client.generate), not prepended
# to the user turn - keeping instructions and the actual question in
# separate chat roles helps, but on its own isn't enough for a weak model
# like tinyllama: it still tends to pattern-match the "##"-header style of
# the input and keep continuing it rather than switching to a new response.
# generate() also passes format="json" to Ollama, which grammar-constrains
# token sampling so the model structurally cannot emit free-text echo - that
# constraint, not prompting alone, is what actually fixes the failure mode.
SYSTEM_PREAMBLE = (
    "You are SENTINEL's incident diagnosis assistant. Ground your diagnosis "
    "ONLY in the runbook provided - never invent a root cause or action "
    "that isn't in it. If the alert doesn't match the runbook well enough "
    "to be confident, say so in root_cause instead of guessing. Respond "
    "with a single JSON object and nothing else - no markdown, no commentary."
)

_ROOT_CAUSE_RE = re.compile(r"Root Cause:\s*(.+)", re.IGNORECASE)
_ACTION_RE = re.compile(r"Recommended Action:\s*(.+)", re.IGNORECASE)
_CITED_RE = re.compile(r"Runbook Cited:\s*(\S+)", re.IGNORECASE)


def build_prompt(
    alert: dict, runbook: Runbook, logs: list[str], deploys: list[dict]
) -> str:
    log_block = "\n".join(logs[-20:]) if logs else "(no recent log lines retrieved)"
    deploy_block = (
        "\n".join(f"- {d.get('revision')} at {d.get('deployed_at')}" for d in deploys)
        if deploys
        else "(no deploys in the lookback window)"
    )
    return f"""## Alert
metric: {alert.get('metric')}
value: {alert.get('value')}
mean baseline: {alert.get('mean')}
stddev: {alert.get('stddev')}
z_score: {alert.get('z_score')}
fired_at: {alert.get('fired_at')}

## Matched runbook: {runbook.id} - {runbook.title}
{runbook.body}

## Recent logs
{log_block}

## Recent deploys
{deploy_block}

## Respond with exactly one JSON object, no other text
{{"root_cause": "<one or two sentences, grounded in the runbook above>", "recommended_action": "<pulled from the runbook's recommended action, or \\"insufficient evidence\\" if you cannot ground one>", "runbook_cited": "{runbook.id}"}}
"""


def parse_response(text: str) -> tuple[str | None, str | None, str | None]:
    """Parses the model's {root_cause, recommended_action, runbook_cited}
    JSON response (the shape Ollama's format="json" grammar-constrains it
    to). Falls back to the older labeled-line format (Root Cause: /
    Recommended Action: / Runbook Cited:) for a model that ignores the JSON
    instruction, then to None for anything else - callers fall back to the
    raw text rather than failing."""
    parsed = _parse_json_fields(text)
    if parsed is not None:
        return parsed
    return (
        _first_match(_ROOT_CAUSE_RE, text),
        _first_match(_ACTION_RE, text),
        _first_match(_CITED_RE, text),
    )


def _parse_json_fields(text: str) -> tuple[str | None, str | None, str | None] | None:
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        data = json.loads(text[start:end])
    except (ValueError, AttributeError):
        return None
    if not isinstance(data, dict):
        return None
    return (
        _clean(data.get("root_cause")),
        _clean(data.get("recommended_action")),
        _clean(data.get("runbook_cited")),
    )


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_match(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None
