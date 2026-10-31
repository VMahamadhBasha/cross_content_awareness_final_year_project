"use client";
import { useState } from "react";
import type { Creator, Post } from "@/lib/api";

type Range = 7 | 30 | 90;

function compact(value: number): string {
  return Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function InstagramDashboard({ creators, posts, creatorId }: { creators: Creator[]; posts: Post[]; creatorId: number | null }) {
  const [range, setRange] = useState<Range>(30);
  const instagramCreators = creators.filter((creator) => creator.platforms.includes("instagram") && (creatorId == null || creator.id === creatorId));
  const creatorIds = new Set(instagramCreators.map((creator) => creator.id));
  const followers = instagramCreators.reduce((total, creator) => total + (creator.followers.instagram ?? 0), 0);
  const cutoff = Date.now() - range * 24 * 60 * 60 * 1000;
  const recentPosts = posts.filter((item) =>
    item.platform === "instagram" &&
    creatorIds.has(item.creator_id) &&
    new Date(item.published_at).getTime() >= cutoff,
  );
  const withMetrics = recentPosts.filter((item) => item.metrics != null);
  const totals = withMetrics.reduce((total, item) => ({
    views: total.views + (item.metrics?.views ?? 0),
    likes: total.likes + (item.metrics?.likes ?? 0),
    comments: total.comments + (item.metrics?.comments ?? 0),
    shares: total.shares + (item.metrics?.shares ?? 0),
  }), { views: 0, likes: 0, comments: 0, shares: 0 });
  const interactions = totals.likes + totals.comments + totals.shares;
  const engagementRate = followers > 0 && withMetrics.length > 0
    ? (interactions / withMetrics.length / followers) * 100
    : null;
  const daily = Array.from({ length: range }, (_, index) => {
    const date = new Date(Date.now() - (range - index - 1) * 24 * 60 * 60 * 1000);
    date.setHours(0, 0, 0, 0);
    return { key: date.toLocaleDateString(), label: range === 7 || index % 5 === 0 ? date.toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "", value: 0 };
  });
  const byDay = new Map(daily.map((day) => [day.key, day]));
  for (const item of withMetrics) {
    const date = new Date(item.published_at);
    date.setHours(0, 0, 0, 0);
    const day = byDay.get(date.toLocaleDateString());
    if (day) day.value += (item.metrics?.likes ?? 0) + (item.metrics?.comments ?? 0) + (item.metrics?.shares ?? 0);
  }
  const maxDaily = Math.max(...daily.map((day) => day.value), 1);
  const chartPoints = daily.map((day, index) => `${(index / Math.max(daily.length - 1, 1)) * 100},${92 - (day.value / maxDaily) * 78}`).join(" ");
  const topPosts = [...withMetrics].sort((a, b) =>
    ((b.metrics?.likes ?? 0) + (b.metrics?.comments ?? 0) + (b.metrics?.shares ?? 0)) -
    ((a.metrics?.likes ?? 0) + (a.metrics?.comments ?? 0) + (a.metrics?.shares ?? 0)),
  ).slice(0, 3);

  if (instagramCreators.length === 0) return null;

  return (
    <section className="instagram-dashboard" aria-labelledby="instagram-dashboard-title">
      <div className="instagram-heading">
        <div>
          <div className="eyebrow">PROFESSIONAL DASHBOARD</div>
          <h2 id="instagram-dashboard-title">Instagram insights</h2>
          <p className="muted">Performance from connected professional accounts · based on posts published in this period</p>
        </div>
        <label className="range-picker">Period
          <select value={range} onChange={(event) => setRange(Number(event.target.value) as Range)}>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </label>
      </div>
      <div className="insight-stats">
        <div className="card stat"><div className="label">Followers</div><div className="value">{compact(followers)}</div><div className="sub">Current connected account total</div></div>
        <div className="card stat"><div className="label">Views</div><div className="value">{compact(totals.views)}</div><div className="sub">On {withMetrics.length} posts with metrics</div></div>
        <div className="card stat"><div className="label">Interactions</div><div className="value">{compact(interactions)}</div><div className="sub">{compact(totals.likes)} likes · {compact(totals.comments)} comments · {compact(totals.shares)} shares</div></div>
        <div className="card stat"><div className="label">Avg. engagement rate</div><div className="value">{engagementRate == null ? "–" : `${engagementRate.toFixed(2)}%`}</div><div className="sub">Interactions per post ÷ current followers</div></div>
      </div>
      <div className="instagram-content-grid">
        <div className="card insight-chart">
          <div className="insight-card-heading"><div><h3>Interaction activity</h3><p className="muted">Likes, comments and shares by post publish date</p></div><span className="chart-legend"><i /> Interactions</span></div>
          {withMetrics.length === 0 ? <div className="empty compact-empty">No Instagram post metrics for this period yet. Sync your connected account to see insights.</div> : (
            <div className="activity-chart">
              <div className="chart-y-labels"><span>{compact(maxDaily)}</span><span>{compact(maxDaily / 2)}</span><span>0</span></div>
              <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`Daily Instagram interactions over the last ${range} days`}>
                {[14, 53, 92].map((y) => <line key={y} x1="0" x2="100" y1={y} y2={y} className="chart-grid-line" />)}
                <polyline points={chartPoints} className="activity-line" />
              </svg>
              <div className="chart-x-labels">{daily.map((day, index) => <span key={index}>{day.label}</span>)}</div>
            </div>
          )}
          <p className="data-note">Views and interactions are the metrics available from the current connection; reach, profile visits and audience demographics are not provided by this app.</p>
        </div>
        <div className="card top-content">
          <div className="insight-card-heading"><div><h3>Top content</h3><p className="muted">Ranked by likes, comments and shares</p></div></div>
          {topPosts.length === 0 ? <div className="empty compact-empty">Top posts will appear after Instagram data is synced.</div> : topPosts.map((item, index) => (
            <div className="top-post-row" key={item.id}>
              <span className="rank">{index + 1}</span>
              <div className="top-post-copy"><strong>{item.kind}</strong><span>{item.caption || "No caption"} </span></div>
              <strong>{compact((item.metrics?.likes ?? 0) + (item.metrics?.comments ?? 0) + (item.metrics?.shares ?? 0))}</strong>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
