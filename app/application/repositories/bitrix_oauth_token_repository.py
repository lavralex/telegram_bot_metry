from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.infrastructure.database.models import BitrixOAuthToken


class BitrixOAuthTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)

    def get_by_portal(self, portal: str) -> Optional[BitrixOAuthToken]:
        return self.db.query(BitrixOAuthToken).filter(BitrixOAuthToken.portal == portal).first()

    def get_by_portal_for_update(self, portal: str) -> Optional[BitrixOAuthToken]:
        return (
            self.db.query(BitrixOAuthToken)
            .filter(BitrixOAuthToken.portal == portal)
            .with_for_update()
            .first()
        )

    def create_if_missing(self, portal: str) -> BitrixOAuthToken:
        row = self.get_by_portal(portal)
        if row:
            return row
        row = BitrixOAuthToken(
            portal=portal,
            access_token=None,
            refresh_token=None,
            expires_at=None,
            is_valid=False,
            version=1,
            created_at=self.now_utc(),
            updated_at=self.now_utc(),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def upsert_tokens(
        self,
        *,
        portal: str,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
    ) -> BitrixOAuthToken:
        row = self.get_by_portal(portal)
        if not row:
            row = BitrixOAuthToken(
                portal=portal,
                created_at=self.now_utc(),
                version=1,
            )
            self.db.add(row)
            self.db.flush()

        row.access_token = access_token
        row.refresh_token = refresh_token
        row.expires_at = expires_at
        row.is_valid = True
        row.version = int(row.version or 0) + 1
        row.updated_at = self.now_utc()
        self.db.flush()
        return row

    def invalidate(self, row: BitrixOAuthToken) -> BitrixOAuthToken:
        row.access_token = None
        row.refresh_token = None
        row.expires_at = None
        row.is_valid = False
        row.version = int(row.version or 0) + 1
        row.updated_at = self.now_utc()
        self.db.flush()
        return row
