"""Instagram API with Instagram Login connector for professional accounts and webhook signature checks."""
import hashlib
import hmac
from datetime import datetime

import httpx

from app.content.descriptors import extract_hashtags
from app.schemas import Platform, RawMetrics, RawPost

GRAPH = "https://graph.instagram.com/v26.0"
MEDIA_FIELDS = "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count"


def verify_signature(body: bytes, header: str | None, app_secret: str | None) -> bool:
    """Validate the X-Hub-Signature-256 header of a webhook delivery."""
    if not app_secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    return hmac.compare_digest(header[7:], hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest())


def parse_media(item: dict, extra: dict | None = None) -> RawPost:
    """Normalise an Instagram media object into the unified schema."""
    extra = extra or {}
    caption = item.get("caption", "") or ""
    kind = "reel" if item.get("media_product_type") == "REELS" else "video" if item.get("media_type") == "VIDEO" else "image"
    return RawPost(platform=Platform.INSTAGRAM, external_id=item["id"], kind=kind, caption=caption, hashtags=extract_hashtags(caption), media_url=item.get("media_url"), thumbnail_url=item.get("thumbnail_url") or (item.get("media_url") if kind == "image" else None), permalink=item.get("permalink"), published_at=datetime.fromisoformat(item["timestamp"].replace("+0000", "+00:00")), metrics=RawMetrics(views=int(extra.get("views", 0)), likes=int(item.get("like_count", 0)), comments=int(item.get("comments_count", 0)), shares=int(extra.get("shares", 0))))


class InstagramConnector:
    """Fetches recent media and insights for the account the access token belongs to."""

    def __init__(self, access_token: str) -> None:
        self.token = access_token

    def _get(self, path: str, **params) -> dict:
        """Perform an authenticated GET request."""
        r = httpx.get(f"{GRAPH}/{path}", params={**params, "access_token": self.token}, timeout=20)
        r.raise_for_status()
        return r.json()

    def resolve_account(self, identifier: str) -> dict:
        """Resolve the token-authorized professional account by username or Instagram user ID."""
        identifier = identifier.strip().lstrip("@")
        response = self._get(
            "me", fields="user_id,username,name,followers_count"
        )
        if isinstance(response.get("data"), list):
            if len(response["data"]) != 1:
                raise ValueError("Instagram did not return one connected account.")
            profile = response["data"][0]
        else:
            profile = response

        account_id = profile.get("user_id")
        username = profile.get("username")
        if not isinstance(account_id, (str, int)) or not isinstance(username, str):
            raise ValueError(
                "Instagram did not return the professional account ID and username."
            )
        try:
            followers = int(profile.get("followers_count", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Instagram returned an invalid follower count.") from exc
        account_id = str(account_id)
        if identifier.casefold() not in {account_id.casefold(), username.casefold()}:
            raise PermissionError(
                "The configured Instagram token is not authorized for that account. "
                "Instagram Login only exposes the professional account connected to this token."
            )
        return {
            "id": account_id,
            "username": username,
            "name": profile.get("name") or username,
            "followers": followers,
        }

    def _insights(self, media_id: str) -> dict:
        """Read views and shares insights, tolerating metrics unsupported for a media type."""
        try:
            data = self._get(f"{media_id}/insights", metric="views,shares").get("data", [])
            return {m["name"]: m["values"][0]["value"] for m in data}
        except httpx.HTTPError:
            return {}

    def fetch_recent(self, account_id: str = "me", limit: int = 25) -> tuple[list[RawPost], int]:
        """Return recent media with engagement counters and the follower count."""
        me = self._get(account_id, fields="followers_count")
        items = self._get(f"{account_id}/media", fields=MEDIA_FIELDS, limit=limit).get("data", [])
        return [parse_media(i, self._insights(i["id"])) for i in items], int(me.get("followers_count", 0))
