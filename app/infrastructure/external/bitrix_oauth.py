import asyncio
import aiohttp
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import config
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

OAUTH_TOKEN_URL = getattr(config, "BITRIX24_OAUTH_TOKEN_URL", "https://oauth.bitrix.info/oauth/token/")


def _dbg() -> bool:
    return bool(getattr(config, "BITRIX24_DEBUG", False)) and not bool(getattr(config, "is_production", False))


def _mask(s: Optional[str]) -> str:
    if not s:
        return ""
    s = str(s)
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{s[-4:]}"


@dataclass
class OAuthToken:
    access_token: str
    refresh_token: str
    expires_at: datetime


class BitrixOAuthStorage:
    """
    Хранилище токенов в БД.
    Храним на "техническом пользователе" user_id=0 в bot_users.user_metadata.
    """

    def load(self) -> Optional[OAuthToken]:
        db = SessionLocal()
        try:
            from app.infrastructure.database.models import BotUser

            row = db.query(BotUser).filter(BotUser.user_id == 0).first()
            if not row or not row.user_metadata:
                if _dbg():
                    logger.warning("BitrixOAuthStorage.load: no system BotUser or empty metadata")
                return None

            meta = row.user_metadata
            tok = meta.get("bitrix_oauth")
            if not tok:
                if _dbg():
                    logger.warning("BitrixOAuthStorage.load: no bitrix_oauth key in metadata")
                return None

            expires_at = datetime.fromisoformat(tok["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            else:
                expires_at = expires_at.astimezone(timezone.utc)

            access = tok.get("access_token") or ""
            refresh = tok.get("refresh_token") or ""

            if _dbg():
                logger.warning(
                    "BitrixOAuthStorage.load: loaded token from DB user_id=0 expires_at=%s access=%s refresh=%s",
                    expires_at.isoformat(),
                    _mask(access),
                    _mask(refresh),
                )

            if not access or not refresh:
                return None

            return OAuthToken(
                access_token=access,
                refresh_token=refresh,
                expires_at=expires_at,
            )
        finally:
            db.close()

    def save(self, token: OAuthToken) -> None:
        db = SessionLocal()
        try:
            from app.infrastructure.database.models import BotUser

            row = db.query(BotUser).filter(BotUser.user_id == 0).first()
            created = False
            if not row:
                row = BotUser(user_id=0, username="system", first_name="System", last_name="OAuth")
                db.add(row)
                db.commit()
                db.refresh(row)
                created = True

            meta = row.user_metadata or {}
            meta["bitrix_oauth"] = {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expires_at": token.expires_at.astimezone(timezone.utc).isoformat(),
            }
            row.user_metadata = meta
            db.commit()

            if _dbg():
                logger.warning(
                    "BitrixOAuthStorage.save: saved token to DB user_id=0 created=%s expires_at=%s access=%s refresh=%s",
                    created,
                    token.expires_at.astimezone(timezone.utc).isoformat(),
                    _mask(token.access_token),
                    _mask(token.refresh_token),
                )
        finally:
            db.close()


class BitrixOAuthService:
    _refresh_lock = asyncio.Lock()

    def __init__(self):
        self.storage = BitrixOAuthStorage()

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _is_expiring(expires_at: datetime, skew_seconds: int = 120) -> bool:
        return expires_at <= (BitrixOAuthService._now_utc() + timedelta(seconds=skew_seconds))

    def _bootstrap_from_env_if_needed(self) -> Optional[OAuthToken]:
        access = getattr(config, "BITRIX24_OAUTH_ACCESS_TOKEN", None)
        refresh = getattr(config, "BITRIX24_OAUTH_REFRESH_TOKEN", None)

        if not access or not refresh:
            if _dbg():
                logger.warning("BitrixOAuth bootstrap: no env tokens present")
            return None

        default_expires_in = int(getattr(config, "BITRIX24_OAUTH_EXPIRES_IN", 3600))
        token = OAuthToken(
            access_token=str(access),
            refresh_token=str(refresh),
            expires_at=self._now_utc() + timedelta(seconds=default_expires_in),
        )

        self.storage.save(token)

        logger.info("✅ Bitrix OAuth bootstrap: токены загружены из env и сохранены в БД")
        if _dbg():
            logger.warning(
                "BitrixOAuth bootstrap details: expires_in=%s expires_at=%s access=%s refresh=%s",
                default_expires_in,
                token.expires_at.isoformat(),
                _mask(token.access_token),
                _mask(token.refresh_token),
            )

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

        if _dbg():
            logger.warning(
                "BitrixOAuth get_access_token: expires_at=%s expiring=%s portal=%s token_url=%s client_id=%s",
                token.expires_at.isoformat(),
                self._is_expiring(token.expires_at),
                getattr(config, "BITRIX24_PORTAL", ""),
                OAUTH_TOKEN_URL,
                _mask(getattr(config, "BITRIX24_CLIENT_ID", "")),
            )

        if not self._is_expiring(token.expires_at):
            return token.access_token

        logger.info("🔄 Bitrix OAuth: обновляем access_token по refresh_token...")


        async with self._refresh_lock:
            # После ожидания лока перечитаем токен — возможно, другой воркер уже обновил его
            token2 = self.storage.load()
            if token2 and not self._is_expiring(token2.expires_at):
                return token2.access_token
            if token2:
                token = token2

            payload = {
                "grant_type": "refresh_token",
                "client_id": config.BITRIX24_CLIENT_ID,
                "client_secret": config.BITRIX24_CLIENT_SECRET,
                "refresh_token": token.refresh_token,
            }

            timeout = aiohttp.ClientTimeout(total=20)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(OAUTH_TOKEN_URL, data=payload) as resp:
                    status = resp.status
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        text = await resp.text()
                        raise RuntimeError(f"Bitrix token refresh non-JSON: {status}: {text[:300]}")

            if _dbg():
                safe = dict(data) if isinstance(data, dict) else {"_": str(data)}
                if isinstance(safe, dict):
                    if "access_token" in safe:
                        safe["access_token"] = "***"
                    if "refresh_token" in safe:
                        safe["refresh_token"] = "***"
                logger.warning("BitrixOAuth refresh response: status=%s data=%s", status, safe)

            if not isinstance(data, dict) or "access_token" not in data:
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
