import re

from .runbooks import Runbook

_SYSTEM_PREAMBLE = (
    "You are SENTINEL's incident diagnosis assistant. You must ground your "
    "diagnosis ONLY in the runbook provided below - do not invent root "
    "causes or remediation steps that are not in it. If the alert and "
    "evidence do not match the runbook well enough to be confident, say so "
    "explicitly instead of guessing."
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
    return f"""{_SYSTEM_PREAMBLE}

## Alert
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

## Respond in exactly this format
Root Cause: <one or two sentences, grounded in the runbook above>
Recommended Action: <pulled from the runbook's recommended action, or "insufficient evidence" if you cannot ground one>
Runbook Cited: {runbook.id}
"""


def parse_response(text: str) -> tuple[str | None, str | None, str | None]:
    """Pull the three labeled fields back out of the LLM's plain-text
    response. Returns (root_cause, recommended_action, cited_runbook_id),
    with None for any field the model didn't produce in the expected shape
    - callers fall back to the raw text rather than failing."""
    return (
        _first_match(_ROOT_CAUSE_RE, text),
        _first_match(_ACTION_RE, text),
        _first_match(_CITED_RE, text),
    )


def _first_match(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None
