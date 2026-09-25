import re
from collections import Counter

from .runbooks import Runbook

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _runbook_text(runbook: Runbook) -> str:
    return " ".join(
        [runbook.title, " ".join(runbook.signals), " ".join(runbook.tags), runbook.body]
    )


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[token] * b[token] for token in common)
    norm_a = sum(v * v for v in a.values()) ** 0.5
    norm_b = sum(v * v for v in b.values()) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def rank_runbooks(
    context: str, candidates: list[Runbook]
) -> list[tuple[Runbook, float]]:
    """Rank candidates by lexical overlap between `context` and each runbook's
    title/signals/tags/body. Pure term-overlap (no embeddings, no network
    call) so ranking is deterministic and testable offline."""
    query_vec = Counter(tokenize(context))
    scored = [
        (rb, _cosine(query_vec, Counter(tokenize(_runbook_text(rb)))))
        for rb in candidates
    ]
    return sorted(scored, key=lambda pair: pair[1], reverse=True)


def match_runbook(metric: str, context: str, runbooks: list[Runbook]) -> Runbook | None:
    """Ground retrieval in a direct metric match first - a runbook is only a
    candidate if it explicitly covers the alerting metric. This is what
    keeps the diagnosis agent from citing an irrelevant runbook: if nothing
    covers this metric, the caller gets None back and must withhold
    diagnosis rather than guess."""
    candidates = [rb for rb in runbooks if metric in rb.metrics]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    ranked = rank_runbooks(context, candidates)
    return ranked[0][0]
