"use client";
import type { Contribution } from "@/lib/api";

export function Sparkline({ values, color = "#5546c8", width = 90, height = 26 }: { values: number[]; color?: string; width?: number; height?: number }) {
  if (values.length < 2) return <span className="muted">–</span>;
  const max = Math.max(...values), min = Math.min(...values), span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * width},${height - 2 - ((v - min) / span) * (height - 4)}`).join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function TimelineChart({ actual, expected }: { actual: { hours: number; weighted: number }[]; expected: { hours: number; expected: number }[] }) {
  const W = 500, H = 214, P = { l: 58, r: 12, t: 12, b: 44 };
  const xs = [...actual.map((a) => a.hours), ...expected.map((e) => e.hours)], ys = [...actual.map((a) => a.weighted), ...expected.map((e) => e.expected)];
  const xMax = Math.max(...xs, 1), yMax = Math.max(...ys, 1) * 1.1;
  const sx = (x: number) => P.l + (x / xMax) * (W - P.l - P.r), sy = (y: number) => H - P.b - (y / yMax) * (H - P.t - P.b);
  const line = (pts: [number, number][]) => pts.map(([x, y]) => `${sx(x)},${sy(y)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Actual versus expected engagement">
      {[0, 0.5, 1].map((t) => (
        <g key={t}>
          <line x1={P.l} x2={W - P.r} y1={sy(yMax * t)} y2={sy(yMax * t)} stroke="#dce1eb" />
          <text x={P.l - 6} y={sy(yMax * t) + 4} fill="#626b7e" fontSize="10" textAnchor="end">{Math.round(yMax * t)}</text>
        </g>
      ))}
      {[0, 0.25, 0.5, 0.75, 1].map((t) => <text key={t} x={sx(xMax * t)} y={H - P.b + 15} fill="#626b7e" fontSize="10" textAnchor="middle">{Math.round(xMax * t)}h</text>)}
      <text x={(P.l + W - P.r) / 2} y={H - 4} fill="#626b7e" fontSize="11" textAnchor="middle">Hours since post</text>
      <text x={15} y={(P.t + H - P.b) / 2} fill="#626b7e" fontSize="11" textAnchor="middle" transform={`rotate(-90 15 ${(P.t + H - P.b) / 2})`}>Engagement</text>
      <polyline points={line(expected.map((e) => [e.hours, e.expected]))} fill="none" stroke="#147a91" strokeWidth={2} strokeDasharray="5 4" />
      <polyline points={line(actual.map((a) => [a.hours, a.weighted]))} fill="none" stroke="#5546c8" strokeWidth={2.5} />
      {actual.map((a, i) => <circle key={i} cx={sx(a.hours)} cy={sy(a.weighted)} r={3} fill="#5546c8" />)}
    </svg>
  );
}

export function ContributionBars({ items }: { items: Contribution[] }) {
  const max = Math.max(...items.map((i) => Math.abs(i.contribution)), 0.01);
  return (
    <div className="bars">
      {items.map((c) => (
        <div className="bar" key={c.feature} title={`${c.feature} = ${c.value}`}>
          <span>{c.feature.replace(/_/g, " ")}</span>
          <div className="track">
            <div className="mid" />
            <div className={`fill ${c.contribution >= 0 ? "pos" : "neg"}`} style={{ width: `${(Math.abs(c.contribution) / max) * 50}%` }} />
          </div>
          <span style={{ textAlign: "right" }}>{c.contribution >= 0 ? "+" : ""}{c.contribution.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}
