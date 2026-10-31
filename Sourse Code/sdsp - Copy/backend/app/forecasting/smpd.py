"""Loader for SMPD-Image and SMPD-Video style CSV files with configurable column mapping."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.content.descriptors import build_descriptors, extract_hashtags
from app.content.embeddings import get_text_embedder

DEFAULT_MAP = {"user": "Uid", "caption": "Title", "tags": "Alltags", "time": "Postdate", "label": "label", "duration": None}


def _parse_time(value) -> datetime:
    """Parse a unix timestamp or ISO date string into an aware UTC datetime."""
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return pd.to_datetime(value, utc=True).to_pydatetime()


def load_smpd(posts_csv: str, label_file: str | None = None, kind: str = "image", column_map: dict | None = None, limit: int | None = None) -> tuple[list[dict], np.ndarray]:
    """Load SMPD posts into forecaster rows and relative-popularity targets using each user's prior mean as the baseline."""
    cm = {**DEFAULT_MAP, **(column_map or {})}
    df = pd.read_csv(posts_csv, nrows=limit)
    if label_file:
        df["label"] = np.loadtxt(label_file)[: len(df)]
    missing = [cm[k] for k in ("user", "caption", "time", "label") if cm[k] not in df.columns]
    if missing:
        raise ValueError(f"missing columns {missing}; pass column_map to match your SMPD files, available: {list(df.columns)}")
    df["_t"] = df[cm["time"]].map(_parse_time)
    df = df.sort_values("_t").reset_index(drop=True)
    global_mean = float(df[cm["label"]].mean())
    history: dict = {}
    captions = [str(c) + " " + str(t if pd.notna(t) else "") for c, t in zip(df[cm["caption"]].fillna(""), df[cm["tags"]] if cm["tags"] in df.columns else [""] * len(df))]
    embeddings = get_text_embedder().embed(captions)
    rows, targets = [], []
    for i, rec in df.iterrows():
        user, label = rec[cm["user"]], float(rec[cm["label"]])
        past = history.setdefault(user, [])
        baseline = float(np.mean(past)) if past else global_mean
        tags = extract_hashtags(captions[i]) or [t for t in str(rec.get(cm["tags"], "")).split() if t]
        duration = float(rec[cm["duration"]]) if cm["duration"] and cm["duration"] in df.columns and pd.notna(rec[cm["duration"]]) else (None if kind == "image" else 30.0)
        desc = build_descriptors(str(rec[cm["caption"]]), tags, "image" if kind == "image" else "video", duration, rec["_t"])
        rows.append({"descriptors": desc, "text_embedding": embeddings[i].tolist(), "visual_embedding": None, "platform": "instagram", "baseline": max(baseline, 0.0), "followers": len(past)})
        targets.append(label - baseline)
        past.append(label)
    return rows, np.asarray(targets)
