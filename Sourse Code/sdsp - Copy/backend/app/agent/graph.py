"""LangGraph workflow: retrieve, generate, verify grounding, retry once, then fall back to rules."""
import logging
from typing import TypedDict

from sqlalchemy.orm import Session

from app.agent.grounding import verify
from app.agent.llm import RuleBasedLLM, make_llm
from app.agent.rag import SimilarPostRetriever, build_evidence
from app.agent.types import AgentContext, AgentResult, Evidence
from app.config import get_settings

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 2


class AgentState(TypedDict, total=False):
    """State passed between graph nodes."""

    ctx: AgentContext
    session: Session
    evidence: list[Evidence]
    draft: dict
    score: float
    first_score: float | None
    attempts: int
    passed: bool
    fallback: bool
    backend: str
    result: AgentResult


class RecommendationAgent:
    """Event-driven agent grounding LLM advice in the forecast, its attributions and similar past posts."""

    def __init__(self, llm=None) -> None:
        self.llm, self.rules, self.retriever = llm or make_llm(), RuleBasedLLM(), SimilarPostRetriever()
        self.threshold = get_settings().grounding_threshold
        self._graph = self._build_graph()

    def _retrieve(self, state: AgentState) -> AgentState:
        """Retrieve similar past posts and build the evidence list."""
        ctx = state["ctx"]
        ctx.similar = self.retriever.search(state["session"], ctx.creator_id, ctx.embedding, ctx.post_id)
        return {"evidence": build_evidence(ctx), "attempts": 0, "first_score": None, "fallback": False}

    def _generate(self, state: AgentState) -> AgentState:
        """Ask the LLM for a draft, treating failures as an empty draft."""
        attempt = state.get("attempts", 0)
        try:
            draft = self.llm.generate(state["ctx"], state["evidence"], attempt)
        except Exception as exc:
            log.warning("LLM backend %s failed: %s", self.llm.name, exc)
            draft = {"summary": "", "actions": []}
        return {"draft": draft, "attempts": attempt + 1, "backend": self.llm.name}

    def _verify(self, state: AgentState) -> AgentState:
        """Verify the draft against the evidence."""
        report = verify(state["draft"], state["evidence"])
        first = state.get("first_score")
        return {"score": report.score, "first_score": report.score if first is None else first, "passed": report.score >= self.threshold and bool(report.passed_actions), "draft": {**state["draft"], "actions": report.passed_actions or state["draft"].get("actions", [])} if report.score >= self.threshold else state["draft"]}

    def _route(self, state: AgentState) -> str:
        """Choose the next node after verification."""
        if state["passed"]:
            return "finalize"
        return "generate" if state["attempts"] < MAX_ATTEMPTS and self.llm.name != "rules" else "fallback"

    def _fallback(self, state: AgentState) -> AgentState:
        """Use the deterministic rule-based recommender, which only states evidence-backed facts."""
        draft = self.rules.generate(state["ctx"], state["evidence"])
        return {"draft": draft, "fallback": self.llm.name != "rules", "backend": "rules"}

    def _finalize(self, state: AgentState) -> AgentState:
        """Assemble the result object."""
        d = state["draft"]
        used = {c for a in d["actions"] for c in a.get("evidence", [])}
        evidence = [e for e in state["evidence"] if e.id in used or e.id == "F1"]
        return {"result": AgentResult(d.get("summary", ""), d["actions"], evidence, float(state.get("first_score") or 0.0), state.get("fallback", False), state.get("backend", self.llm.name))}

    def _build_graph(self):
        """Compile the LangGraph graph when langgraph is installed, otherwise return None."""
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return None
        g = StateGraph(AgentState)
        for name, fn in [("retrieve", self._retrieve), ("generate", self._generate), ("verify", self._verify), ("fallback", self._fallback), ("finalize", self._finalize)]:
            g.add_node(name, fn)
        g.set_entry_point("retrieve")
        g.add_edge("retrieve", "generate")
        g.add_edge("generate", "verify")
        g.add_conditional_edges("verify", self._route, {"finalize": "finalize", "generate": "generate", "fallback": "fallback"})
        g.add_edge("fallback", "finalize")
        g.add_edge("finalize", END)
        return g.compile()

    def _run_manual(self, state: AgentState) -> AgentState:
        """Run the same nodes sequentially when langgraph is unavailable."""
        state.update(self._retrieve(state))
        while True:
            state.update(self._generate(state))
            state.update(self._verify(state))
            nxt = self._route(state)
            if nxt == "generate":
                continue
            if nxt == "fallback":
                state.update(self._fallback(state))
            state.update(self._finalize(state))
            return state

    def run(self, session: Session, ctx: AgentContext, use_langgraph: bool = True) -> AgentResult:
        """Produce a grounded recommendation for the context."""
        state: AgentState = {"ctx": ctx, "session": session}
        final = self._graph.invoke(state) if (self._graph is not None and use_langgraph) else self._run_manual(state)
        return final["result"]
