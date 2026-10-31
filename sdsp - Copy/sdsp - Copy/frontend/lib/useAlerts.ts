"use client";
import { useEffect, useRef, useState } from "react";
import { get, wsUrl, type Recommendation } from "./api";

export function useAlerts(creatorId: number | null) {
  const [alerts, setAlerts] = useState<Recommendation[]>([]);
  const [connected, setConnected] = useState(false);
  const creatorRef = useRef(creatorId);
  creatorRef.current = creatorId;

  useEffect(() => {
    get<Recommendation[]>(`/api/recommendations?limit=25${creatorId ? `&creator_id=${creatorId}` : ""}`).then(setAlerts).catch(() => setAlerts([]));
  }, [creatorId]);

  useEffect(() => {
    let ws: WebSocket | null = null, timer: ReturnType<typeof setTimeout>, closed = false;
    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => setConnected(true);
      ws.onclose = () => { setConnected(false); if (!closed) timer = setTimeout(connect, 2000); };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        if (msg.type !== "alert") return;
        const rec: Recommendation = msg.recommendation;
        const wanted = creatorRef.current;
        if (wanted && (rec as unknown as { creator_id: number }).creator_id !== wanted) return;
        setAlerts((prev) => (prev.some((p) => p.id === rec.id) ? prev : [rec, ...prev].slice(0, 40)));
      };
    };
    connect();
    return () => { closed = true; clearTimeout(timer); ws?.close(); };
  }, []);

  return { alerts, connected };
}
