"use client";
import { useEffect, useState } from "react";
import { fmt, get, pct, type PostDetail } from "@/lib/api";
import { ContributionBars, TimelineChart } from "./Charts";

export function PostDrawer({ postId, onClose }: { postId: string; onClose: () => void }) {
  const [post, setPost] = useState<PostDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    get<PostDetail>(`/api/posts/${encodeURIComponent(postId)}`).then(setPost).catch((e) => setError(String(e)));
  }, [postId]);

  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer">
        <div className="row"><h2 style={{ margin: 0 }}>Post analysis</h2><span className="spacer" /><button onClick={onClose}>Close</button></div>
        {error && <p className="error">{error}</p>}
        {!post && !error && <p className="muted">Loading…</p>}
        {post && (
          <>
            <div className="row" style={{ marginTop: 14 }}><span className={`chip ${post.platform}`}>{post.platform}</span><span className={`badge ${post.status}`}>{post.status.replace("_", " ")}</span><span className="muted">{post.creator}</span></div>
            <p className="caption">{post.caption}</p>
            {post.metrics && post.forecast && (
              <div className="stats" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
                <div className="card stat"><div className="label">Engagement now</div><div className="value">{fmt(post.metrics.weighted)}</div><div className="sub">{post.metrics.hours.toFixed(1)}h after publishing</div></div>
                <div className="card stat"><div className="label">Forecast final</div><div className="value">{fmt(post.forecast.predicted_value)}</div><div className="sub">baseline {fmt(post.forecast.baseline)}</div></div>
                <div className="card stat"><div className="label">Vs baseline</div><div className="value">{pct(post.forecast.pct_vs_baseline)}</div><div className="sub">{post.forecast.cold_start ? "cold start" : "predicted"}</div></div>
              </div>
            )}
            <h2>Actual vs expected trajectory</h2>
            <div className="card"><TimelineChart actual={post.timeline} expected={post.expected_curve} /><div className="meta"><span style={{ color: "#7c5cff" }}>━ actual</span><span style={{ color: "#22d3ee" }}>╌ forecast trajectory</span></div></div>
            <h2 style={{ marginTop: 18 }}>Why this forecast</h2>
            <div className="card"><ContributionBars items={post.explanation} /></div>
          </>
        )}
      </aside>
    </>
  );
}
