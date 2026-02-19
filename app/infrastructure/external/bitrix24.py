from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp

from app.core.config import config
from app.infrastructure.external.bitrix_oauth import BitrixOAuthService

logger = logging.getLogger(__name__)


class BitrixWebhookClient:

    def __init__(self, webhook_url: str):
        self.base = (webhook_url or "").rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "BitrixWebhookClient":
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.session:
            await self.session.close()

    async def post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.base:
            return {"success": False, "error": "BITRIX24_WEBHOOK_URL is empty"}
        if not self.session:
            raise RuntimeError("BitrixWebhookClient session is not initialized")

        url = f"{self.base}/{method}"

        try:
            async with self.session.post(url, json=payload) as resp:
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.exception("Bitrix webhook request failed: %s %s", method, e)
            return {"success": False, "error": f"Request failed: {e}"}

        if isinstance(data, dict) and data.get("error"):
            logger.error("Bitrix webhook error (%s): %s", method, data)
            return {
                "success": False,
                "error": data.get("error"),
                "error_description": data.get("error_description"),
                "raw": data,
            }

        return {"success": True, "result": data.get("result") if isinstance(data, dict) else data}


class BitrixOAuthRestClient:

    def __init__(self, portal: str, oauth: BitrixOAuthService):
        self.portal = (portal or "").strip()
        self.oauth = oauth
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "BitrixOAuthRestClient":
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.session:
            await self.session.close()

    def _base_url(self) -> str:
        if not self.portal:
            return ""
        if self.portal.startswith("http://") or self.portal.startswith("https://"):
            return self.portal.rstrip("/")
        return f"https://{self.portal}".rstrip("/")

    async def post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.session:
            raise RuntimeError("BitrixOAuthRestClient session is not initialized")

        base = self._base_url()
        if not base:
            return {"success": False, "error": "BITRIX24_PORTAL is empty (required for OAuth mode)"}

        token = await self.oauth.get_access_token()
        if not token:
            return {"success": False, "error": "OAuth token is missing (install app / obtain tokens first)"}

        url = f"{base}/rest/{method}.json"
        body = dict(payload)
        body.setdefault("auth", token)

        try:
            async with self.session.post(url, json=body) as resp:
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.exception("Bitrix OAuth request failed: %s %s", method, e)
            return {"success": False, "error": f"Request failed: {e}"}

        if isinstance(data, dict) and data.get("error"):
            logger.error("Bitrix OAuth error (%s): %s", method, data)
            return {
                "success": False,
                "error": data.get("error"),
                "error_description": data.get("error_description"),
                "raw": data,
            }

        return {"success": True, "result": data.get("result") if isinstance(data, dict) else data}


def _is_enabled() -> bool:
    return bool(getattr(config, "BITRIX24_ENABLED", False))


def _use_oauth() -> bool:
    return bool(getattr(config, "BITRIX24_USE_OAUTH", False))


def _webhook_url() -> str:
    return str(getattr(config, "BITRIX24_WEBHOOK_URL", "") or "").rstrip("/")


def _portal() -> str:
    return str(getattr(config, "BITRIX24_PORTAL", "") or "").strip()


def _lead_source_id() -> str:
    return str(getattr(config, "BITRIX24_TELEGRAM_SOURCE_ID", "") or "").strip()


def _openlines_line_id() -> str:
    return str(getattr(config, "BITRIX24_OPENLINE_ID", "") or "").strip()


def _openlines_connector_id() -> str:
    return str(getattr(config, "BITRIX24_CONNECTOR_ID", "") or "").strip()


async def _post_bitrix(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:

    if _use_oauth():
        oauth = BitrixOAuthService()
        async with BitrixOAuthRestClient(_portal(), oauth) as bx:
            return await bx.post(method, payload)

    async with BitrixWebhookClient(_webhook_url()) as bx:
        return await bx.post(method, payload)


async def ensure_bitrix_lead(lead_obj: Any, fields: Dict[str, Any]) -> Dict[str, Any]:
    if not _is_enabled():
        return {"success": False, "error": "BITRIX24_ENABLED=false"}

    if not _use_oauth() and not _webhook_url():
        return {"success": False, "error": "BITRIX24_WEBHOOK_URL is empty (webhook mode)"}
    if _use_oauth() and not _portal():
        return {"success": False, "error": "BITRIX24_PORTAL is empty (oauth mode)"}

    bitrix_lead_id = getattr(lead_obj, "bitrix_lead_id", None)

    source_id = _lead_source_id()
    if source_id and "SOURCE_ID" not in fields:
        fields["SOURCE_ID"] = source_id

    fields.setdefault("OPENED", "Y")
    fields.setdefault("STATUS_ID", "NEW")

    fields.setdefault("timestamp", datetime.now().isoformat())

    if bitrix_lead_id:
        payload = {"id": int(bitrix_lead_id), "fields": fields}
        res = await _post_bitrix("crm.lead.update", payload)
        if res.get("success"):
            return {"success": True, "lead_id": int(bitrix_lead_id), "created": False}
        return res

    payload = {"fields": fields}
    res = await _post_bitrix("crm.lead.add", payload)
    if res.get("success"):
        try:
            new_id = int(res["result"])
        except Exception:
            return {"success": False, "error": "Unexpected crm.lead.add response", "raw": res}
        return {"success": True, "lead_id": new_id, "created": True}

    return res


async def send_message_to_openlines(
    *,
    lead_id: int,
    tg_user_id: int,
    tg_username: str,
    text: str,
    message_id: str,
    unix_date: int,
) -> Dict[str, Any]:
    """
    Отправка сообщения в Открытую линию через коннектор.
    В OAuth-режиме это обязательно (иначе WRONG_AUTH_TYPE).
    """
    if not _is_enabled():
        return {"success": False, "error": "BITRIX24_ENABLED=false"}

    if not _use_oauth() and not _webhook_url():
        return {"success": False, "error": "BITRIX24_WEBHOOK_URL is empty (webhook mode)"}
    if _use_oauth() and not _portal():
        return {"success": False, "error": "BITRIX24_PORTAL is empty (oauth mode)"}

    line = _openlines_line_id()
    if not line:
        return {"success": False, "error": "BITRIX24_OPENLINE_ID (LINE) is empty"}

    connector = _openlines_connector_id()
    if not connector:
        return {"success": False, "error": "BITRIX24_CONNECTOR_ID (CONNECTOR) is empty"}

    user_display = f"@{tg_username}" if tg_username else str(tg_user_id)

    payload = {
        "CONNECTOR": connector,
        "LINE": line,
        "MESSAGES": [
            {
                "user": {"id": str(tg_user_id), "name": user_display},
                "message": {"id": str(message_id), "date": int(unix_date), "text": text},
                "chat": {"id": str(tg_user_id), "name": f"Telegram {tg_user_id}"},
                "crm": {"lead": int(lead_id)} if int(lead_id) > 0 else {},
            }
        ],
    }

    logger.info(
        "📨 OpenLines send: mode=%s connector=%s line=%s tg_user_id=%s msg_id=%s",
        "oauth" if _use_oauth() else "webhook",
        connector,
        line,
        tg_user_id,
        message_id,
    )

    res = await _post_bitrix("imconnector.send.messages", payload)

    if not res.get("success"):
        logger.warning("⚠️ OpenLines send failed: %s %s", res.get("error"), res.get("error_description"))
    else:
        logger.info("✅ OpenLines send OK: %s", str(res.get("result"))[:200])

    return res
