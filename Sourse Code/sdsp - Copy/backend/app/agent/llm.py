"""LLM backends: deterministic rule-based fallback and OpenAI-compatible hosted APIs."""
import json
import math

from app.agent.rag import NON_ACTIONABLE
from app.agent.types import AgentContext, Evidence
from app.config import get_settings
from app.llm_client import chat_completion_json

SYSTEM_PROMPT = (
    "You are a social media strategist. Using ONLY the numbered evidence provided, write recommendations for the creator. "
    'Respond with JSON only: {"summary": str, "actions": [{"action": str, "rationale": str, "evidence": [ids]}]}. '
    "Every action must cite one or more evidence ids such as F1, X2, S1 or D1. Any number you mention must appear in the cited evidence. Give 3 to 5 specific actions."
)

ADVICE = {
    "has_question": "Close the caption with a question to invite comments",
    "has_cta": "Add a clear call to action such as follow, save or comment",
    "hashtag_count": "Change the hashtag set (currently {v:.0f}) to a focused group of topical tags",
    "hour": "Test a different posting hour; the {v:.0f}:00 UTC slot is pulling the forecast down",
    "day_of_week": "Try a different weekday for this kind of post",
    "is_weekend": "Reconsider weekend timing for this audience",
    "caption_words": "Rework the caption length (currently {v:.0f} words) to match your stronger posts",
    "emoji_count": "Adjust emoji use in the caption to match your stronger posts",
    "exclamations": "Tone down the exclamation marks in the caption",
    "duration_s": "Revisit the video length ({v:.0f} seconds) because it is lowering the forecast",
    "is_short_video": "Reconsider the short-video format for this idea",
    "is_video": "Reconsider the media format for this idea",
    "caption_semantics": "Reframe the caption topic closer to what your audience engaged with before",
    "visual_content": "Replace the thumbnail or opening frames with visuals closer to your top posts",
    "brightness": "Adjust the brightness of the thumbnail or opening frames",
    "colorfulness": "Adjust the color intensity of the thumbnail or opening frames",
    "speech_wpm": "Adjust the speaking pace in the opening seconds",
    "transcript_words": "Adjust how much is said in the video",
}

KEEP = {
    "has_question": "Keep the closing question in the caption",
    "has_cta": "Keep the call to action in the caption",
    "hashtag_count": "Keep the current hashtag count ({v:.0f})",
    "hour": "Keep the {v:.0f}:00 UTC posting slot",
    "caption_words": "Keep the caption length ({v:.0f} words)",
    "is_short_video": "Keep the short-video format",
    "duration_s": "Keep the video length ({v:.0f} seconds)",
    "caption_semantics": "Keep the caption topic and framing",
    "visual_content": "Keep the visual style of the thumbnail or opening frames",
}


def _ev(evidence: list[Evidence], prefix: str) -> list[Evidence]:
    """Return evidence items whose id starts with the prefix."""
    return [e for e in evidence if e.id.startswith(prefix)]


class RuleBasedLLM:
    """Offline recommender that composes advice directly from the evidence so every claim is grounded."""

    name = "rules"

    def generate(self, ctx: AgentContext, evidence: list[Evidence], attempt: int = 0) -> dict:
        """Compose a recommendation from the forecast attributions, detections and similar posts."""
        f, actions = ctx.forecast, []
        pct = (math.exp(f.predicted_relative) - 1.0) * 100.0
        feats = [(e, c) for e, c in zip(_ev(evidence, "X"), [c for c in f.explanation if c.feature not in NON_ACTIONABLE])]
        negatives = [(e, c) for e, c in feats if c.contribution < -0.02]
        positives = [(e, c) for e, c in feats if c.contribution > 0.02]
        sims, det = _ev(evidence, "S"), _ev(evidence, "D")
        if ctx.event_type == "underperformance":
            summary = f"This post is running behind its forecast ({det[0].text})."
            actions.append({"action": "Reply to every comment now and pin a question that invites answers", "rationale": f"Early engagement is the lever left: {det[0].text}.", "evidence": ["D1"]})
        elif ctx.event_type == "comment_surge":
            summary = f"Comments are spiking on this post ({det[0].text})."
            actions.append({"action": "Reply to the most active commenters within the hour while the thread is hot", "rationale": f"Spike detected: {det[0].text}.", "evidence": ["D1"]})
            actions.append({"action": "Pin a comment that points viewers to your next post or a follow action", "rationale": "A surge is the best moment to convert attention, and the forecast shows the baseline expectation.", "evidence": ["D1", "F1"]})
        else:
            summary = f"Forecast: this post is expected to land {pct:+.0f}% versus your usual performance."
            if ctx.mode == "event":
                actions.append({"action": "Stay active in the comments during the first hour after publishing", "rationale": f"The forecast is {pct:+.0f}% versus baseline, and early replies are the main controllable factor.", "evidence": ["F1"]})
        for e, c in negatives[:2]:
            base = ADVICE.get(c.feature, "Revisit " + c.feature.replace("_", " ")).format(v=c.value)
            ref = f" Compare with {sims[0].id}, which shows how a past post of yours performed." if sims else ""
            actions.append({"action": base, "rationale": f"{e.text}.{ref}", "evidence": [e.id] + ([sims[0].id] if sims else [])})
        if positives:
            e, c = positives[0]
            actions.append({"action": KEEP.get(c.feature, "Keep " + c.feature.replace("_", " ") + " unchanged").format(v=c.value), "rationale": f"{e.text}.", "evidence": [e.id]})
        if sims and len(actions) < 4:
            actions.append({"action": "Reuse the structure of your closest past post", "rationale": sims[0].text + ".", "evidence": [sims[0].id]})
        return {"summary": summary, "actions": actions}


class _JsonLLM:
    """Shared prompt building and JSON parsing for chat-style LLM backends."""

    name = "llm"

    def _prompt(self, ctx: AgentContext, evidence: list[Evidence], attempt: int) -> str:
        """Build the user prompt listing the situation and the evidence."""
        lines = [f"Situation: {ctx.event_type or 'draft analysis'} on {ctx.platform}.", f"Caption: {ctx.caption[:300]}", "Evidence:"] + [f"[{e.id}] {e.text}" for e in evidence]
        if attempt:
            lines.append("Your previous answer cited unknown ids or numbers that are not in the evidence. Cite only listed ids and reuse numbers exactly.")
        return "\n".join(lines)

    @staticmethod
    def _parse(raw: str) -> dict:
        """Parse a JSON object from the model output."""
        raw = raw.strip()
        start, end = raw.find("{"), raw.rfind("}")
        return json.loads(raw[start : end + 1])


class OpenAICompatLLM(_JsonLLM):
    """Hosted LLM through any OpenAI-compatible chat completions API."""

    name = "openai"

    def generate(self, ctx: AgentContext, evidence: list[Evidence], attempt: int = 0) -> dict:
        """Call the chat completions endpoint in JSON mode."""
        return self._parse(chat_completion_json(SYSTEM_PROMPT, self._prompt(ctx, evidence, attempt)))


class GeminiLLM(OpenAICompatLLM):
    """Gemini backend using the shared provider client."""

    name = "gemini"


def make_llm():
    """Create the configured LLM backend."""
    backend = get_settings().llm_backend
    return {"openai": OpenAICompatLLM, "gemini": GeminiLLM}.get(backend, RuleBasedLLM)()
