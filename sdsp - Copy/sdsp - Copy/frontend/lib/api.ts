export type Platform = "youtube" | "instagram";
export type Status = "new" | "behind" | "on_track" | "ahead" | "unknown";

export interface Creator { id: number; name: string; platforms: Platform[]; followers: Record<string, number> }
export interface CreatorAccountInput { name: string; platform: Platform; external_id: string; handle?: string }
export interface InstagramCreatorResponse {
  creator: Creator;
  instagram_account: { id: string; username: string; followers: number };
}
export interface Metrics { views: number; likes: number; comments: number; shares: number; weighted: number; hours: number }
export interface ForecastSummary { baseline: number; predicted_value: number; predicted_relative: number; pct_vs_baseline: number; cold_start: boolean }
export interface Contribution { feature: string; value: number; contribution: number }
export interface Post {
  id: string; creator_id: number; creator: string; platform: Platform; kind: string; caption: string; hashtags: string[];
  published_at: string; thumbnail_url: string | null; permalink: string | null; sparkline: number[];
  metrics: Metrics | null; forecast: ForecastSummary | null; status: Status; trajectory_ratio?: number;
}
export interface PostDetail extends Post {
  descriptors: Record<string, number>; explanation: Contribution[];
  timeline: { hours: number; weighted: number; comments: number; likes: number; views: number }[];
  expected_curve: { hours: number; expected: number }[];
}
export interface Evidence { id: string; text: string }
export interface Action { action: string; rationale: string; evidence: string[] }
export interface Recommendation {
  id: number; summary: string; actions: Action[]; evidence: Evidence[]; grounding_score: number; fallback_used: boolean;
  llm_backend: string; latency_ms: number | null; created_at: string; helpful: boolean | null;
  event?: { id: string; type: string; occurred_at: string; payload: Record<string, number> };
  post?: { id: string; platform: Platform; caption: string };
}
export interface Stats {
  posts: number; posts_by_platform: Record<string, number>; events_by_type: Record<string, number>;
  latency: { count: number; p50_ms: number; p95_ms: number }; grounding: { mean_score: number; grounded_share: number };
  usefulness: { rated: number; helpful: number; helpful_share: number };
  fallback_share: number; model_version: string | null;
}
export interface Health {
  status: string; demo_mode: boolean; bus: string; llm: string; langgraph: boolean; connectors: string[];
  forecaster: { ready: boolean; backend: string; model_version: string | null; mode: string; message: string };
}
export interface Variant { label: string; predicted_relative: number; delta_pct: number }
export interface WhatIfResult {
  forecast: { baseline: number; predicted_relative: number; predicted_value: number; explanation: Contribution[]; cold_start: boolean };
  variants: Variant[];
  recommendation: { summary: string; actions: Action[]; evidence: Evidence[]; grounding_score: number; llm_backend: string; fallback_used: boolean };
}

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const wsUrl = () => API.replace(/^http/, "ws") + "/ws/alerts";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, { ...init, headers: { "Content-Type": "application/json" }, cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}
export const get = <T,>(path: string) => request<T>(path);
export const post = <T,>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });
export const remove = <T,>(path: string) => request<T>(path, { method: "DELETE" });

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
export const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : Math.round(n).toString());
export const pct = (n: number) => `${n >= 0 ? "+" : ""}${Math.round(n)}%`;
