import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n?(.*)$", re.DOTALL)


@dataclass
class Runbook:
    id: str
    title: str
    metrics: list[str]
    signals: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    safe_actions: list[str] = field(default_factory=list)
    approval_required: bool = True
    rollback: str = ""
    body: str = ""
    path: str = ""


def _parse_file(path: Path) -> Runbook:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"runbook {path} is missing YAML frontmatter")
    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()
    return Runbook(
        id=meta.get("id", path.stem),
        title=meta.get("title", path.stem),
        metrics=list(meta.get("metrics", [])),
        signals=list(meta.get("signals", [])),
        tags=list(meta.get("tags", [])),
        safe_actions=list(meta.get("safe_actions", [])),
        approval_required=bool(meta.get("approval_required", True)),
        rollback=meta.get("rollback", ""),
        body=body,
        path=str(path),
    )


def load_runbooks(directory: str | Path) -> list[Runbook]:
    """Load every runbook markdown file in `directory` (skips README.md)."""
    directory = Path(directory)
    return [
        _parse_file(path)
        for path in sorted(directory.glob("*.md"))
        if path.name.lower() != "readme.md"
    ]
