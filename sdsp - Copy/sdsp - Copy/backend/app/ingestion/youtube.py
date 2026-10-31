"""YouTube Data API v3 connector and PubSubHubbub push-notification helpers."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from app.content.descriptors import extract_hashtags
from app.schemas import Platform, RawMetrics, RawPost

API = "https://www.googleapis.com/youtube/v3"
HUB = "https://pubsubhubbub.appspot.com/subscribe"
DURATION_RE = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?")
ATOM = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def parse_duration(iso: str) -> float:
    """Convert a YouTube ISO 8601 duration, including durations with a day component, to seconds."""
    match = DURATION_RE.fullmatch(iso or "PT0S")
    if match is None:
        raise ValueError(f"Invalid YouTube ISO 8601 video duration: {iso!r}")
    days, hours, minutes, seconds = match.groups()
    if not any((days, hours, minutes, seconds)):
        raise ValueError(f"Invalid YouTube ISO 8601 video duration: {iso!r}")
    if "T" in (iso or "PT0S") and not any((hours, minutes, seconds)):
        raise ValueError(f"Invalid YouTube ISO 8601 video duration: {iso!r}")
    return float(int(days or 0) * 86400 + int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0))


def parse_video(item: dict) -> RawPost:
    """Normalise a YouTube videos.list item into the unified schema."""
    sn, st = item["snippet"], item.get("statistics", {})
    duration = parse_duration(item.get("contentDetails", {}).get("duration", "PT0S"))
    caption = f"{sn.get('title', '')}\n{sn.get('description', '')[:500]}".strip()
    thumbs = sn.get("thumbnails", {})
    thumb = (thumbs.get("high") or thumbs.get("default") or {}).get("url")
    tags = list(dict.fromkeys(extract_hashtags(caption) + [t.lower().replace(" ", "") for t in sn.get("tags", [])]))
    return RawPost(platform=Platform.YOUTUBE, external_id=item["id"], kind="short" if duration <= 60 else "video", caption=caption, hashtags=tags, thumbnail_url=thumb, permalink=f"https://www.youtube.com/watch?v={item['id']}", duration_s=duration, published_at=datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")), metrics=RawMetrics(views=int(st.get("viewCount", 0)), likes=int(st.get("likeCount", 0)), comments=int(st.get("commentCount", 0)), shares=0))


class YouTubeConnector:
    """Fetches a channel's recent uploads and statistics with an API key."""

    def __init__(self, api_key: str) -> None:
        self.key = api_key

    def _get(self, path: str, **params) -> dict:
        """Perform an authenticated GET request."""
        r = httpx.get(f"{API}/{path}", params={**params, "key": self.key}, timeout=20)
        r.raise_for_status()
        return r.json()

    def fetch_recent(self, channel_id: str, limit: int = 50) -> tuple[list[RawPost], int]:
        """Return the most recent uploads and the subscriber count of a channel."""
        ch = self._get("channels", part="contentDetails,statistics", id=channel_id)["items"][0]
        uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        ids = [i["contentDetails"]["videoId"] for i in self._get("playlistItems", part="contentDetails", playlistId=uploads, maxResults=min(limit, 50)).get("items", [])]
        items = self._get("videos", part="snippet,contentDetails,statistics", id=",".join(ids)).get("items", []) if ids else []
        return [parse_video(i) for i in items], int(ch.get("statistics", {}).get("subscriberCount", 0))


def parse_push_notification(body: bytes) -> list[tuple[str, str]]:
    """Extract (channel_id, video_id) pairs from a PubSubHubbub Atom notification."""
    root = ET.fromstring(body)
    out = []
    for entry in root.findall("a:entry", ATOM):
        vid, ch = entry.findtext("yt:videoId", namespaces=ATOM), entry.findtext("yt:channelId", namespaces=ATOM)
        if vid and ch:
            out.append((ch, vid))
    return out


def subscribe_channel(channel_id: str, callback_url: str) -> int:
    """Subscribe the callback URL to upload notifications for a channel and return the hub status code."""
    r = httpx.post(HUB, data={"hub.mode": "subscribe", "hub.topic": f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}", "hub.callback": callback_url, "hub.verify": "async"}, timeout=20)
    return r.status_code
