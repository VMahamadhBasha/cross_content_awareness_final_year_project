"use client";
import { useEffect, useState } from "react";
import { post, timeAgo, type Action, type Evidence, type Platform } from "@/lib/api";

const LABEL: Record<string, string> = { new_upload: "New post", underperformance: "Engagement below estimate", comment_surge: "Comments increased", draft: "Draft suggestion" };

interface Props {
  type: string; summary: string; actions: Action[]; evidence: Evidence[]; grounding: number; backend: string; fallback: boolean;
  createdAt?: string; latencyMs?: number | null; platform?: Platform; caption?: string; onOpen?: () => void;
  recommendationId?: number; helpful?: boolean | null; onFeedbackSaved?: () => void;
}

export function RecommendationCard({ type, summary, actions, evidence, grounding, backend, fallback, createdAt, latencyMs, platform, caption, onOpen, recommendationId, helpful, onFeedbackSaved }: Props) {
  const [rating, setRating] = useState<boolean | null>(helpful ?? null);
  const [savingRating, setSavingRating] = useState(false);
  const [ratingError, setRatingError] = useState("");
  useEffect(() => setRating(helpful ?? null), [helpful]);
  const byId = Object.fromEntries(evidence.map((e) => [e.id, e.text]));
  async function rate(value: boolean) {
    if (!recommendationId) return;
    setSavingRating(true);
    setRatingError("");
    try {
      await post(`/api/recommendations/${recommendationId}/feedback`, { helpful: value });
      setRating(value);
      onFeedbackSaved?.();
    } catch (error) {
      setRatingError(`Could not save rating: ${error}`);
    } finally {
      setSavingRating(false);
    }
  }
  return (
    <article className={`card alert ${type}`}>
      <div className="row">
        <span className={`badge ${type}`}>{LABEL[type] ?? type}</span>
        {platform && <span className={`chip ${platform}`}>{platform}</span>}
        <span className="spacer" />
        {createdAt && <span className="muted">{timeAgo(createdAt)}</span>}
      </div>
      {caption && <div className="caption" style={{ cursor: onOpen ? "pointer" : "default" }} onClick={onOpen}>{caption}</div>}
      <div className="summary">{summary}</div>
      <ul className="actions">
        {actions.map((a, i) => (
          <li key={i}>
            <div className="a">{a.action}</div>
            <div className="r">{a.rationale}</div>
            {a.evidence.map((id) => <span key={id} className="ev" title={byId[id] ?? id}>{id}</span>)}
          </li>
        ))}
      </ul>
      <div className="meta">
        <span>grounding {(grounding * 100).toFixed(0)}%</span>
        <span>{backend}{fallback ? " (fallback)" : ""}</span>
        {latencyMs != null && <span>{latencyMs < 1000 ? `${Math.round(latencyMs)} ms` : `${(latencyMs / 1000).toFixed(1)} s`} event → advice</span>}
      </div>
      {recommendationId != null && <div className="feedback">
        <span className="muted">Was this suggestion helpful?</span>
        <button type="button" aria-pressed={rating === true} disabled={savingRating} onClick={() => rate(true)}>{rating === true ? "👍 Yes" : "👍 Yes"}</button>
        <button type="button" aria-pressed={rating === false} disabled={savingRating} onClick={() => rate(false)}>{rating === false ? "👎 No" : "👎 No"}</button>
        {savingRating && <span className="muted" role="status">Saving your vote…</span>}
        {ratingError && <span className="error" role="alert">{ratingError}</span>}
      </div>}
    </article>
  );
}
