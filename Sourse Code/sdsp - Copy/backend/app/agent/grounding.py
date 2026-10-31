"""Grounding verification: every action must cite valid evidence and may only state numbers present in it."""
import re
from dataclasses import dataclass, field

from app.agent.types import Evidence

NUM_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?")


@dataclass
class GroundingReport:
    """Result of verifying a draft recommendation against its evidence."""

    score: float
    passed_actions: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def _numbers(text: str) -> list[float]:
    """Extract numeric values from text."""
    return [float(m) for m in NUM_RE.findall(text)]


def verify(draft: dict, evidence: list[Evidence]) -> GroundingReport:
    """Score a draft by the share of actions that cite valid evidence and make only supported numeric claims."""
    by_id = {e.id: e.text for e in evidence}
    allowed = [n for text in by_id.values() for n in _numbers(text)]
    actions = draft.get("actions") or []
    passed, issues = [], []
    for i, a in enumerate(actions):
        cites = [c for c in (a.get("evidence") or []) if isinstance(c, str)]
        if not str(a.get("action", "")).strip():
            issues.append(f"action {i}: empty")
        elif not cites or any(c not in by_id for c in cites):
            issues.append(f"action {i}: missing or unknown evidence ids {cites}")
        else:
            bad = [n for n in _numbers(f"{a.get('action', '')} {a.get('rationale', '')}") if abs(n) > 3 and not any(abs(n - x) <= max(0.5, 0.02 * abs(x)) for x in allowed)]
            if bad:
                issues.append(f"action {i}: unsupported numbers {bad}")
            else:
                passed.append(a)
    score = len(passed) / len(actions) if actions else 0.0
    return GroundingReport(score, passed, issues)
