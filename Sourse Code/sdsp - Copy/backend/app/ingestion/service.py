"""Scheduled and push-triggered synchronisation of connected accounts."""
import logging

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.ingestion.instagram import InstagramConnector
from app.ingestion.youtube import YouTubeConnector
from app.models import Account

log = logging.getLogger(__name__)


class IngestionService:
    """Polls connectors and feeds normalised posts into the pipeline."""

    def __init__(self, pipeline) -> None:
        s = get_settings()
        self.pipeline = pipeline
        self.connectors = {}
        if s.youtube_api_key:
            self.connectors["youtube"] = YouTubeConnector(s.youtube_api_key)
        if s.instagram_access_token:
            self.connectors["instagram"] = InstagramConnector(s.instagram_access_token)

    @property
    def enabled(self) -> bool:
        """True when at least one real platform connector is configured."""
        return bool(self.connectors)

    def sync_account(self, account_id: int) -> int:
        """Fetch the latest posts of one account and publish the resulting events."""
        with session_scope() as s:
            acc = s.get(Account, account_id)
            platform, external_id = acc.platform, acc.external_id
        connector = self.connectors.get(platform)
        if connector is None:
            return 0
        raws, followers = connector.fetch_recent(external_id)
        with session_scope() as s:
            s.get(Account, account_id).followers = followers
        return self.pipeline.ingest_and_publish(account_id, raws)

    def sync_all(self) -> int:
        """Synchronise every account that has a configured connector."""
        with session_scope() as s:
            ids = [a.id for a in s.scalars(select(Account)) if a.platform in self.connectors]
        total = 0
        for account_id in ids:
            try:
                total += self.sync_account(account_id)
            except Exception:
                log.exception("sync failed for account %s", account_id)
        return total

    def sync_external(self, platform: str, external_id: str) -> int:
        """Synchronise the account matching a platform identity, used by webhooks."""
        with session_scope() as s:
            acc = s.scalar(select(Account).where(Account.platform == platform, Account.external_id == external_id))
            account_id = acc.id if acc else None
        return self.sync_account(account_id) if account_id else 0
