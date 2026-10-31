"""Shared dataclasses for the recommendation agent."""
from dataclasses import dataclass, field

from app.schemas import ForecastResult


@dataclass
class Evidence:
    """A citable fact the agent may ground its advice on."""

    id: str
    text: str


@dataclass
class SimilarPost:
    """A mature past post of the same creator that resembles the current one."""

    post_id: str
    caption: str
    similarity: float
    relative_pct: float
    descriptors: dict


@dataclass
class AgentContext:
    """Everything the agent knows about the post, the event and the creator's history."""

    mode: str
    event_type: str | None
    platform: str
    caption: str
    forecast: ForecastResult
    descriptors: dict
    embedding: list[float]
    creator_id: int
    post_id: str | None = None
    detection: dict | None = None
    similar: list[SimilarPost] = field(default_factory=list)


@dataclass
class AgentResult:
    """The final grounded recommendation."""

    summary: str
    actions: list[dict]
    evidence: list[Evidence]
    grounding_score: float
    fallback_used: bool
    backend: str
