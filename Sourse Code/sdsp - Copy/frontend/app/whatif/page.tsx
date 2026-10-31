"use client";
import { useEffect, useState } from "react";
import { ContributionBars } from "@/components/Charts";
import { RecommendationCard } from "@/components/RecommendationCard";
import { fmt, get, pct, post, type Creator, type Platform, type WhatIfResult } from "@/lib/api";

function localInputValue(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function localDateForUtcHour(selected: string, utcHour: number): string {
  const target = selected ? new Date(selected) : new Date();
  const targetDay = `${target.getFullYear()}-${target.getMonth()}-${target.getDate()}`;
  const candidates = [-1, 0, 1].map((offset) => {
    const candidate = new Date(Date.UTC(target.getFullYear(), target.getMonth(), target.getDate() + offset, utcHour));
    const candidateDay = `${candidate.getFullYear()}-${candidate.getMonth()}-${candidate.getDate()}`;
    return { candidate, matchesDay: candidateDay === targetDay };
  });
  const matching = candidates.find((item) => item.matchesDay);
  return localInputValue((matching ?? candidates[1]).candidate);
}

export default function WhatIf() {
  const [creators, setCreators] = useState<Creator[]>([]);
  const [creatorId, setCreatorId] = useState<number>(0);
  const [platform, setPlatform] = useState<Platform>("instagram");
  const [kind, setKind] = useState("reel");
  const [caption, setCaption] = useState("");
  const [duration, setDuration] = useState(30);
  const [imageDataUrl, setImageDataUrl] = useState<string | null>(null);
  const [when, setWhen] = useState("");
  const [result, setResult] = useState<WhatIfResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { get<Creator[]>("/api/creators").then((c) => { setCreators(c); if (c[0]) setCreatorId(c[0].id); }).catch((e) => setError(String(e))); }, []);

  const kinds = platform === "youtube" ? ["video", "short"] : ["reel", "image"];
  useEffect(() => { if (!kinds.includes(kind)) setKind(kinds[0]); }, [platform]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    setLoading(true); setError("");
    try {
      setResult(await post<WhatIfResult>("/api/whatif", { creator_id: creatorId, platform, caption, kind, duration_s: kind === "image" ? null : duration, scheduled_at: when ? new Date(when).toISOString() : null, image_data_url: imageDataUrl }));
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  };

  const rel = result ? (Math.exp(result.forecast.predicted_relative) - 1) * 100 : 0;
  const maxDelta = result ? Math.max(...result.variants.map((v) => Math.abs(v.delta_pct)), 1) : 1;
  const bestTime = result?.variants
    .filter((variant) => /^Post at \d{2}:00 UTC$/.test(variant.label))
    .sort((a, b) => b.delta_pct - a.delta_pct)[0];
  const bestTimeHour = bestTime ? Number(bestTime.label.match(/\d{2}/)?.[0]) : null;

  return (
    <div className="grid2">
      <section>
        <h2>Add a post</h2>
        <p className="section-help">Enter your draft to get an estimate and a few suggestions. This is an AI estimate, not a guarantee.</p>
        <div className="card form">
          <div className="twocol">
            <label>Whose account?<select value={creatorId} onChange={(e) => setCreatorId(Number(e.target.value))}>{creators.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
            <label>Where will you post it?<select value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}><option value="instagram">Instagram</option><option value="youtube">YouTube</option></select></label>
          </div>
          <div className="twocol">
            <label>Post type<select value={kind} onChange={(e) => setKind(e.target.value)}>{kinds.map((k) => <option key={k}>{k}</option>)}</select></label>
            <label>Video length in seconds<input type="number" min={1} value={duration} disabled={kind === "image"} onChange={(e) => setDuration(Number(e.target.value))} /></label>
          </div>
          <label>What will your post say?<textarea value={caption} placeholder="Write or paste your post caption here" onChange={(e) => setCaption(e.target.value)} /></label>
          <label>Add a picture (optional; it will be sent to the AI service for review)<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) { setImageDataUrl(null); return; }
            if (!["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 5_000_000) {
              setImageDataUrl(null);
              setError("Choose a JPEG, PNG, or WebP image up to 5 MB.");
              e.target.value = "";
              return;
            }
            const reader = new FileReader();
            reader.onload = () => { setImageDataUrl(typeof reader.result === "string" ? reader.result : null); setError(""); };
            reader.onerror = () => setError("Could not read the selected image.");
            reader.readAsDataURL(file);
          }} /></label>
          {imageDataUrl && <p className="muted">Picture added. It will be sent to your configured AI service with the draft.</p>}
          <label>When do you plan to post? (optional)<input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></label>
          <button className="primary" disabled={loading || !creatorId || !caption.trim()} onClick={run}>{loading ? "Preparing estimate…" : "Estimate and get suggestions"}</button>
          {bestTime && bestTimeHour != null && (
            <div className="best-time-card" role="status">
              <div className="best-time-icon" aria-hidden>◷</div>
              <div className="best-time-copy">
                <strong>Best time to upload</strong>
                <span>{bestTime.label.replace("Post at ", "")} · estimated {pct(bestTime.delta_pct)} vs. your selected time</span>
              </div>
              <button type="button" onClick={() => setWhen(localDateForUtcHour(when, bestTimeHour))}>Use this time</button>
              <p>AI estimate based on this draft and account data. Times shown in UTC; this is a suggestion, not a guarantee.</p>
            </div>
          )}
          {!bestTime && <p className="muted timing-hint">Add a caption and run an estimate to get a recommended upload time for this post.</p>}
          {error && <p className="error">{error}</p>}
        </div>
      </section>

      <section>
        <h2>Post performance and suggestions</h2>
        {!result && <div className="card empty">Your result will appear here. Add an account and enter a post idea to begin.</div>}
        {result && (
          <div style={{ display: "grid", gap: 16 }}>
            <div className="card hero">
              <div className="muted">Estimated engagement compared with this account's usual posts</div>
              <div className={`big ${rel >= 0 ? "pos" : "neg"}`}>{pct(rel)}</div>
              <div className="muted">About {fmt(result.forecast.predicted_value)} engagement points. Usual posts: {fmt(result.forecast.baseline)}{result.forecast.cold_start ? " · Not enough past posts for a reliable comparison yet" : ""}</div>
            </div>
            <div className="card"><h2>What affected the estimate?</h2><ContributionBars items={result.forecast.explanation} /></div>
            <div className="card">
              <h2>Changes you could try</h2>
              {result.variants.map((v) => (
                <div className="variant" key={v.label}>
                  <span>{v.label}</span>
                  <div className="track"><div className="mid" /><div className={`fill ${v.delta_pct >= 0 ? "pos" : "neg"}`} style={{ width: `${(Math.abs(v.delta_pct) / maxDelta) * 50}%` }} /></div>
                  <strong style={{ textAlign: "right", color: v.delta_pct >= 0 ? "var(--good)" : "var(--bad)" }}>{pct(v.delta_pct)}</strong>
                </div>
              ))}
            </div>
            <RecommendationCard type="draft" summary={result.recommendation.summary} actions={result.recommendation.actions} evidence={result.recommendation.evidence} grounding={result.recommendation.grounding_score} backend={result.recommendation.llm_backend} fallback={result.recommendation.fallback_used} />
          </div>
        )}
      </section>
    </div>
  );
}
