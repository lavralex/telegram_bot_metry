from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import aiohttp
from sqlalchemy.exc import IntegrityError

from app.application.repositories.bitrix_oauth_token_repository import BitrixOAuthTokenRepository
from app.core.config import config
from app.core.database import SessionLocal
from app.infrastructure.database.models import BotUser

logger = logging.getLogger(__name__)

OAUTH_TOKEN_URL = getattr(config, "BITRIX24_OAUTH_TOKEN_URL", "https://oauth.bitrix.info/oauth/token/")

_INIT_LOCK = threading.Lock()
_INIT_DONE_PORTALS: set[str] = set()


def _dbg() -> bool:
    return bool(getattr(config, "BITRIX24_DEBUG", False)) and not bool(getattr(config, "is_production", False))


def _mask(s: Optional[str]) -> str:
    if not s:
        return ""
    s = str(s)
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{s[-4:]}"


def _normalize_portal(portal: str) -> str:
    raw = (portal or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        p = urlparse(raw)
        return (p.netloc or "").strip().lower()
    return raw.rstrip("/").lower()


def _utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


@dataclass
class OAuthToken:
    access_token: str
    refresh_token: str
    expires_at: datetime


class OAuthReauthRequired(RuntimeError):
    pass


class BitrixOAuthService:
    def __init__(self, portal: Optional[str] = None):
        self.portal = _normalize_portal(portal or getattr(config, "BITRIX24_PORTAL", ""))

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _is_expiring(expires_at: Optional[datetime], skew_seconds: int = 180) -> bool:
        if not expires_at:
            return True
        return _utc(expires_at) <= (BitrixOAuthService._now_utc() + timedelta(seconds=skew_seconds))

    @staticmethod
    def _is_invalid_refresh_error(err: str, desc: str) -> bool:
        e = (err or "").lower()
        d = (desc or "").lower()
        needles = (
            "invalid_grant",
            "invalid_refresh",
            "expired",
            "refresh token",
            "token has expired",
        )
        return any(n in e or n in d for n in needles)

    def _require_portal(self) -> str:
        if not self.portal:
            raise RuntimeError("BITRIX24_PORTAL is empty for OAuth mode")
        return self.portal

    def _legacy_token_from_bot_user(self, db) -> Optional[OAuthToken]:
        row = db.query(BotUser).filter(BotUser.user_id == 0).first()
        if not row or not row.user_metadata:
            return None
        tok = (row.user_metadata or {}).get("bitrix_oauth")
        if not isinstance(tok, dict):
            return None
        access = str(tok.get("access_token") or "").strip()
        refresh = str(tok.get("refresh_token") or "").strip()
        expires_raw = tok.get("expires_at")
        if not access or not refresh or not expires_raw:
            return None
        try:
            expires_at = _utc(datetime.fromisoformat(str(expires_raw)))
        except Exception:
            return None
        return OAuthToken(access_token=access, refresh_token=refresh, expires_at=expires_at)

    def _token_from_env(self) -> Optional[OAuthToken]:
        access = str(getattr(config, "BITRIX24_OAUTH_ACCESS_TOKEN", "") or "").strip()
        refresh = str(getattr(config, "BITRIX24_OAUTH_REFRESH_TOKEN", "") or "").strip()
        if not access or not refresh:
            return None
        expires_in = int(getattr(config, "BITRIX24_OAUTH_EXPIRES_IN", 3600) or 3600)
        return OAuthToken(
            access_token=access,
            refresh_token=refresh,
            expires_at=self._now_utc() + timedelta(seconds=expires_in),
        )

    def _migrate_legacy_once(self) -> None:
        portal = self._require_portal()

        with _INIT_LOCK:
            if portal in _INIT_DONE_PORTALS:
                return

        db = SessionLocal()
        try:
            repo = BitrixOAuthTokenRepository(db)
            existing = repo.get_by_portal(portal)
            if existing:
                with _INIT_LOCK:
                    _INIT_DONE_PORTALS.add(portal)
                return

            migrated = self._legacy_token_from_bot_user(db) or self._token_from_env()

            if migrated:
                with db.begin():
                    repo.upsert_tokens(
                        portal=portal,
                        access_token=migrated.access_token,
                        refresh_token=migrated.refresh_token,
                        expires_at=migrated.expires_at,
                    )
                logger.info(
                    "Bitrix OAuth tokens migrated to dedicated table (portal=%s, expires_at=%s)",
                    portal,
                    migrated.expires_at.isoformat(),
                )
            else:
                with db.begin():
                    repo.create_if_missing(portal)
                logger.info("Bitrix OAuth token row initialized (portal=%s, no tokens yet)", portal)

            with _INIT_LOCK:
                _INIT_DONE_PORTALS.add(portal)

        except IntegrityError:
            db.rollback()
            with _INIT_LOCK:
                _INIT_DONE_PORTALS.add(portal)
        finally:
            db.close()

    def save_oauth_tokens(self, *, access_token: str, refresh_token: str, expires_in: int) -> None:
        portal = self._require_portal()
        expires_at = self._now_utc() + timedelta(seconds=int(expires_in or 3600))

        db = SessionLocal()
        try:
            repo = BitrixOAuthTokenRepository(db)
            with db.begin():
                repo.upsert_tokens(
                    portal=portal,
                    access_token=str(access_token),
                    refresh_token=str(refresh_token),
                    expires_at=expires_at,
                )
            with _INIT_LOCK:
                _INIT_DONE_PORTALS.add(portal)
        finally:
            db.close()

    def get_token_state(self) -> Dict[str, Any]:
        portal = self._require_portal()
        self._migrate_legacy_once()

        db = SessionLocal()
        try:
            repo = BitrixOAuthTokenRepository(db)
            row = repo.get_by_portal(portal)
            if not row:
                return {
                    "portal": portal,
                    "token_present": False,
                    "refresh_present": False,
                    "is_valid": False,
                    "expires_at": None,
                    "seconds_left": None,
                    "version": None,
                }

            expires_at = _utc(row.expires_at) if row.expires_at else None
            seconds_left = int((expires_at - self._now_utc()).total_seconds()) if expires_at else None

            return {
                "portal": row.portal,
                "token_present": bool(row.access_token),
                "refresh_present": bool(row.refresh_token),
                "is_valid": bool(row.is_valid),
                "expires_at": expires_at.isoformat() if expires_at else None,
                "seconds_left": seconds_left,
                "version": int(row.version or 0),
            }
        finally:
            db.close()

    def has_valid_token(self) -> bool:
        st = self.get_token_state()
        return bool(st.get("token_present") and st.get("refresh_present") and st.get("is_valid"))

    async def _refresh_request(self, *, refresh_token: str) -> Dict[str, Any]:
        payload = {
            "grant_type": "refresh_token",
            "client_id": getattr(config, "BITRIX24_CLIENT_ID", ""),
            "client_secret": getattr(config, "BITRIX24_CLIENT_SECRET", ""),
            "refresh_token": refresh_token,
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

        if not isinstance(data, dict):
            raise RuntimeError(f"Bitrix token refresh failed: unexpected response: {type(data).__name__}")

        if data.get("error"):
            err = str(data.get("error") or "")
            desc = str(data.get("error_description") or "")
            if self._is_invalid_refresh_error(err, desc):
                raise OAuthReauthRequired("Bitrix OAuth refresh token is invalid/expired. Reinstall app.")
            raise RuntimeError(f"Bitrix token refresh failed: {err}: {desc}")

        if "access_token" not in data:
            raise RuntimeError(f"Bitrix token refresh failed: {data}")

        return data

    async def get_access_token(self) -> str:
        portal = self._require_portal()
        self._migrate_legacy_once()

        for _ in range(2):
            db = SessionLocal()
            try:
                repo = BitrixOAuthTokenRepository(db)
                with db.begin():
                    row = repo.get_by_portal_for_update(portal)
                    if not row:
                        try:
                            repo.create_if_missing(portal)
                            row = repo.get_by_portal_for_update(portal)
                        except IntegrityError:
                            raise

                    if not row:
                        raise RuntimeError("Bitrix OAuth token row is missing")

                    if not bool(row.is_valid):
                        raise OAuthReauthRequired("Bitrix OAuth tokens are invalid. Reinstall app.")

                    if not row.refresh_token:
                        raise OAuthReauthRequired("Bitrix OAuth refresh_token is missing. Reinstall app.")

                    if row.access_token and not self._is_expiring(row.expires_at):
                        return row.access_token

                    logger.info(
                        "Bitrix OAuth token refresh started (portal=%s, expires_at=%s, version=%s)",
                        portal,
                        _utc(row.expires_at).isoformat() if row.expires_at else None,
                        row.version,
                    )

                    try:
                        data = await self._refresh_request(refresh_token=row.refresh_token)
                    except OAuthReauthRequired:
                        repo.invalidate(row)
                        logger.error("Bitrix OAuth requires reauthorization (portal=%s)", portal)
                        raise

                    expires_in = int(data.get("expires_in", 3600))
                    new_access = str(data["access_token"])
                    new_refresh = str(data.get("refresh_token") or row.refresh_token)
                    new_expires = self._now_utc() + timedelta(seconds=expires_in)

                    repo.upsert_tokens(
                        portal=portal,
                        access_token=new_access,
                        refresh_token=new_refresh,
                        expires_at=new_expires,
                    )
                    logger.info(
                        "Bitrix OAuth token refreshed (portal=%s, expires_in=%s, version=%s)",
                        portal,
                        expires_in,
                        row.version,
                    )
                    return new_access
            except IntegrityError:
                db.rollback()
                continue
            finally:
                db.close()

        raise RuntimeError("Bitrix OAuth token row contention. Retry request.")
