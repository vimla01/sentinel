import re

_CATEGORY_PATTERNS = {
    "restart": re.compile(r"\brestart\b", re.IGNORECASE),
    "scale": re.compile(r"\bscale\b", re.IGNORECASE),
    "rollback": re.compile(r"\broll[\s-]?back\b", re.IGNORECASE),
}

SAFE_CATEGORIES = frozenset(_CATEGORY_PATTERNS)


def classify(action_text: str) -> str:
    """Maps a runbook's free-text recommended action to one of the three
    hardcoded safe-action categories this platform ever auto-executes -
    restart, scale, rollback - or "unknown" for anything else."""
    for category, pattern in _CATEGORY_PATTERNS.items():
        if pattern.search(action_text or ""):
            return category
    return "unknown"


def should_auto_execute(diagnosis: dict) -> bool:
    """A diagnosis auto-executes only if its runbook explicitly marked the
    action as not requiring approval AND the classified action is one of
    the three hardcoded safe categories. This is a deliberate AND: a
    runbook with approval_required=true always goes to Slack even if its
    action text happens to say "restart" - the category alone is never
    enough to bypass a human."""
    if diagnosis.get("approval_required", True):
        return False
    return classify(diagnosis.get("recommended_action", "")) in SAFE_CATEGORIES
