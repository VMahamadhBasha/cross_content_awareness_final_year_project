"use client";
import { Sparkline } from "@/components/Charts";
import { CreatorForm } from "@/components/CreatorForm";
import { InstagramDashboard } from "@/components/InstagramDashboard";
import { PostDrawer } from "@/components/PostDrawer";
import { RecommendationCard } from "@/components/RecommendationCard";
import { fmt, get, pct, post, remove, type Creator, type Health, type Post, type Stats } from "@/lib/api";
import { useAlerts } from "@/lib/useAlerts";
import { useCallback, useEffect, useState } from "react";

export default function Dashboard() {
  const [creators, setCreators] = useState<Creator[]>([]);
  const [creatorId, setCreatorId] = useState<number | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [removingCreator, setRemovingCreator] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const { alerts, connected } = useAlerts(creatorId);

  const refresh = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([get<Post[]>(`/api/posts?limit=100${creatorId ? `&creator_id=${creatorId}` : ""}`), get<Stats>("/api/stats")]);
      setPosts(p); setStats(s); setError("");
    } catch (e) { setError(`Cannot reach the API: ${e}`); }
  }, [creatorId]);

  useEffect(() => {
    get<Creator[]>("/api/creators").then((c) => { setCreators(c); }).catch((e) => setError(`Cannot reach the API: ${e}`));
    const updateHealth = () => get<Health>("/api/health").then(setHealth).catch(() => undefined);
    updateHealth();
    const interval = window.setInterval(updateHealth, 10000);
    return () => window.clearInterval(interval);
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { if (alerts.length) refresh(); }, [alerts.length, refresh]);

  const syncAccounts = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await post<{ status: string }>("/api/sync", {});
      setNotice("Sync started. Posts will appear when the connected platform accounts have been fetched.");
    } catch (e) {
      setError(`Could not sync accounts: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const removeSelectedCreator = async () => {
    const creator = creators.find((item) => item.id === creatorId);
    if (!creator) return;
    const confirmed = window.confirm(
      `Remove ${creator.name} from this dashboard?\n\nThis deletes its locally stored accounts, posts, metrics, forecasts, alerts, and feedback, and stops future syncing for those accounts. It does not revoke your platform API credentials.`,
    );
    if (!confirmed) return;

    setRemovingCreator(true);
    setError("");
    setNotice("");
    try {
      await remove<{ creator_id: number; deleted: boolean }>(`/api/creators/${creator.id}`);
      const remainingCreators = creators.filter((item) => item.id !== creator.id);
      setCreators(remainingCreators);
      setPosts((current) => current.filter((item) => item.creator_id !== creator.id));
      if (selected) setSelected(null);
      setCreatorId(remainingCreators[0]?.id ?? null);
      setNotice(`${creator.name} was removed. Its locally stored data is deleted and it will no longer be synced.`);
    } catch (e) {
      setError(`Could not remove ${creator.name}: ${e}`);
    } finally {
      setRemovingCreator(false);
    }
  };

  return (
    <>
      <div className="toolbar">
        <label className="filter-label">Show
          <select value={creatorId ?? ""} onChange={(e) => setCreatorId(e.target.value ? Number(e.target.value) : null)} aria-label="Choose creator">
            <option value="">All creators</option>
          {creators.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.platforms.join(" + ")}</option>)}
          </select>
        </label>
        <button type="button" onClick={removeSelectedCreator} disabled={creatorId == null || removingCreator || busy} title={creatorId == null ? "Select a creator to remove" : "Remove this creator and stop syncing its accounts"}>{removingCreator ? "Removing…" : "Remove creator"}</button>
        <span className="live"><span className={`dot ${connected ? "on" : ""}`} />{connected ? "Updates connected" : "Connecting to updates…"}</span>
        <span className="spacer" />
        {!health?.connectors.length && <span className="muted">Add a YouTube or Instagram API key in the backend settings to fetch posts.</span>}
        <button type="button" onClick={syncAccounts} disabled={busy || !health?.connectors.length} title={!health?.connectors.length ? "Add a platform API key in the backend settings first" : undefined}>{busy ? "Fetching posts…" : "Fetch latest posts"}</button>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      <section className="intro">
        <h1>Your creator activity, in one place</h1>
        <p>Connect a YouTube channel or Instagram professional account to see its posts, engagement, and suggestions. Start by adding an account below.</p>
      </section>
      <CreatorForm onCreated={(creator) => {
        setCreators((current) => [...current.filter((item) => item.id !== creator.id), creator]);
        setCreatorId(creator.id);
        setNotice(`${creator.name} was added. Fetch posts to see their latest activity.`);
      }} />

      <InstagramDashboard creators={creators} posts={posts} creatorId={creatorId} />

      <section className="stats">
        <div className="card stat"><div className="label">Posts found</div><div className="value">{stats?.posts ?? "–"}</div><div className="sub">{stats ? Object.entries(stats.posts_by_platform).map(([k, v]) => `${k} ${v}`).join(" · ") : "Posts fetched from connected accounts"}</div></div>
        <div className="card stat"><div className="label">Alerts</div><div className="value">{stats ? Object.values(stats.events_by_type).reduce((a, b) => a + b, 0) : "–"}</div><div className="sub">When a new post appears or engagement changes</div></div>
        <div className="card stat"><div className="label">Time to get a suggestion</div><div className="value">{stats?.latency.count ? `${(stats.latency.p50_ms / 1000).toFixed(1)} s` : "–"}</div><div className="sub">{stats?.latency.count ? "Typical time after an alert" : "No suggestions yet"}</div></div>
        <div className="card stat"><div className="label">Advice supported by post data</div><div className="value">{stats?.latency.count ? `${Math.round(stats.grounding.grounded_share * 100)}%` : "–"}</div><div className="sub">Backup suggestions used {stats ? Math.round(stats.fallback_share * 100) : 0}% of the time</div></div>
        <div className="card stat"><div className="label">Suggestions marked helpful</div><div className="value">{stats?.usefulness.rated ? `${Math.round(stats.usefulness.helpful_share * 100)}%` : "–"}</div><div className="sub">{stats?.usefulness.rated ? `${stats.usefulness.helpful} helpful out of ${stats.usefulness.rated} votes` : "Use the buttons on a suggestion to rate it"}</div></div>
        <div className="card stat"><div className="label">Post estimate service</div><div className="value" style={{ fontSize: 20, paddingTop: 5 }}>{health?.forecaster.ready ? "Ready" : "Not set up"}</div><div className="sub">{health?.forecaster.ready ? "Estimates use the configured AI model" : health?.forecaster.message ?? "Checking setup…"}</div></div>
      </section>

      <div className="grid2">
        <section>
          <h2>Alerts and suggestions</h2>
          <div className="feed">
            {alerts.length === 0 && <div className="card empty">No suggestions yet. Fetch posts from a connected account to get started.</div>}
            {alerts.map((a) => (
              <RecommendationCard key={a.id} recommendationId={a.id} helpful={a.helpful} onFeedbackSaved={refresh} type={a.event?.type ?? "draft"} summary={a.summary} actions={a.actions} evidence={a.evidence} grounding={a.grounding_score} backend={a.llm_backend} fallback={a.fallback_used} createdAt={a.created_at} latencyMs={a.latency_ms} platform={a.post?.platform} caption={a.post?.caption} onOpen={a.post ? () => setSelected(a.post!.id) : undefined} />
            ))}
          </div>
        </section>

        <section>
          <h2>Recent posts</h2>
          <div className="card" style={{ padding: 8, overflow: "auto" }}>
            <table className="posts-table">
              <thead><tr><th>Post</th><th>Engagement trend</th><th>Engagement now</th><th>Estimated total</th><th>Compared with estimate</th></tr></thead>
              <tbody>
                {posts.map((p) => (
                  <tr key={p.id} onClick={() => setSelected(p.id)}>
                    <td><div className="row"><span className={`chip ${p.platform}`}>{p.platform === "youtube" ? "YT" : "IG"}</span><span className="cap" title={p.caption}>{p.caption}</span></div></td>
                    <td><Sparkline values={p.sparkline} color={p.status === "behind" ? "#c2413b" : "#5b4bdb"} /></td>
                    <td>{p.metrics ? fmt(p.metrics.weighted) : "–"}</td>
                    <td>{p.forecast ? <>{fmt(p.forecast.predicted_value)} <span className="muted">({pct(p.forecast.pct_vs_baseline)})</span></> : "–"}</td>
                    <td><span className={`badge ${p.status}`}>{({ new: "Too soon to compare", behind: "Below estimate", on_track: "Near estimate", ahead: "Above estimate", unknown: "No estimate yet" } as Record<string, string>)[p.status]}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {posts.length === 0 && <div className="empty">{creators.length === 0 ? "No accounts added yet. Add a YouTube channel or Instagram professional account above." : "No posts found yet. Check that the platform API key is set up, then fetch posts."}</div>}
          </div>
        </section>
      </div>
      {selected && <PostDrawer postId={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
