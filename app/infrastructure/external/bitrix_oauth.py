import aiohttp
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import config
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

OAUTH_TOKEN_URL = getattr(config, "BITRIX24_OAUTH_TOKEN_URL", "https://oauth.bitrix.info/oauth/token/")


@dataclass
class OAuthToken:
    access_token: str
    refresh_token: str
    expires_at: datetime


class BitrixOAuthStorage:
    """
    Простейшее хранилище токенов в БД.
    Храним на "техническом пользователе" user_id=0 в bot_users.user_metadata.
    """

    def load(self) -> Optional[OAuthToken]:
        db = SessionLocal()
        try:
            from app.infrastructure.database.models import BotUser

            row = db.query(BotUser).filter(BotUser.user_id == 0).first()
            if not row or not row.user_metadata:
                return None

            meta = row.user_metadata
            tok = meta.get("bitrix_oauth")
            if not tok:
                return None

            expires_at = datetime.fromisoformat(tok["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            else:
                expires_at = expires_at.astimezone(timezone.utc)

            return OAuthToken(
                access_token=tok["access_token"],
                refresh_token=tok["refresh_token"],
                expires_at=expires_at,
            )
        finally:
            db.close()

    def save(self, token: OAuthToken) -> None:
        db = SessionLocal()
        try:
            from app.infrastructure.database.models import BotUser

            row = db.query(BotUser).filter(BotUser.user_id == 0).first()
            if not row:
                row = BotUser(user_id=0, username="system", first_name="System", last_name="OAuth")
                db.add(row)
                db.commit()
                db.refresh(row)

            meta = row.user_metadata or {}
            meta["bitrix_oauth"] = {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expires_at": token.expires_at.astimezone(timezone.utc).isoformat(),
            }
            row.user_metadata = meta
            db.commit()
        finally:
            db.close()


class BitrixOAuthService:
    def __init__(self):
        self.storage = BitrixOAuthStorage()

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _is_expiring(expires_at: datetime, skew_seconds: int = 120) -> bool:
        return expires_at <= (BitrixOAuthService._now_utc() + timedelta(seconds=skew_seconds))

    def _bootstrap_from_env_if_needed(self) -> Optional[OAuthToken]:
        """
        Если в БД токенов нет — попробуем взять из env и сохранить.
        Это нужно для DEV/мока, чтобы не падать при первом запуске.
        """
        access = getattr(config, "BITRIX24_OAUTH_ACCESS_TOKEN", None)
        refresh = getattr(config, "BITRIX24_OAUTH_REFRESH_TOKEN", None)

        if not access or not refresh:
            return None

        default_expires_in = int(getattr(config, "BITRIX24_OAUTH_EXPIRES_IN", 3600))
        token = OAuthToken(
            access_token=str(access),
            refresh_token=str(refresh),
            expires_at=self._now_utc() + timedelta(seconds=default_expires_in),
        )

        self.storage.save(token)
        logger.info("✅ Bitrix OAuth bootstrap: токены загружены из env и сохранены в БД")
        return token

    async def get_access_token(self) -> str:
        token = self.storage.load()

        if not token:
            token = self._bootstrap_from_env_if_needed()

        if not token:
            raise RuntimeError(
                "Bitrix OAuth токены не инициализированы. "
                "Нужно задать BITRIX24_OAUTH_ACCESS_TOKEN / BITRIX24_OAUTH_REFRESH_TOKEN "
                "или пройти OAuth и сохранить токены."
            )

        if not self._is_expiring(token.expires_at):
            return token.access_token

        logger.info("🔄 Bitrix OAuth: обновляем access_token по refresh_token...")

        payload = {
            "grant_type": "refresh_token",
            "client_id": config.BITRIX24_CLIENT_ID,
            "client_secret": config.BITRIX24_CLIENT_SECRET,
            "refresh_token": token.refresh_token,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(OAUTH_TOKEN_URL, data=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                try:
                    data = await resp.json()
                except Exception:
                    text = await resp.text()
                    raise RuntimeError(f"Bitrix token refresh non-JSON: {resp.status}: {text[:300]}")

        if "access_token" not in data:
            raise RuntimeError(f"Bitrix token refresh failed: {data}")

        expires_in = int(data.get("expires_in", 3600))
        new_token = OAuthToken(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", token.refresh_token),
            expires_at=self._now_utc() + timedelta(seconds=expires_in),
        )

        self.storage.save(new_token)
        logger.info("✅ Bitrix OAuth: access_token обновлен, expires_in=%s", expires_in)
        return new_token.access_token
