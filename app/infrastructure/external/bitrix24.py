from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import aiohttp

from app.core.config import config
from app.infrastructure.external.bitrix_oauth import BitrixOAuthService

logger = logging.getLogger(__name__)


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


def _public_base_url() -> str:
    return str(getattr(config, "PUBLIC_BASE_URL", "") or "").rstrip("/")


def _connector_name() -> str:
    return str(getattr(config, "BITRIX24_CONNECTOR_NAME", "") or "Metri Telegram Bot").strip()


def _dbg() -> bool:
    return bool(getattr(config, "BITRIX24_DEBUG", False)) and not bool(getattr(config, "is_production", False))


def _dbg_limit() -> int:
    try:
        return int(getattr(config, "BITRIX24_DEBUG_HTTP_BODY_LIMIT", 4000) or 4000)
    except Exception:
        return 4000


def _truncate(s: str, limit: int) -> str:
    if s is None:
        return ""
    s = str(s)
    if len(s) <= limit:
        return s
    return s[:limit] + f"...(truncated, len={len(s)})"


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)


def _mask_webhook_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        host = p.netloc or p.path.split("/")[0]
        return f"{p.scheme}://{host}/rest/***/***"
    except Exception:
        return "***"


def _safe_base_info() -> Dict[str, Any]:
    mode = "oauth" if _use_oauth() else "webhook"
    portal = _portal()
    webhook = _webhook_url()
    return {
        "mode": mode,
        "portal": portal if portal else "",
        "webhook": _mask_webhook_url(webhook) if webhook else "",
    }


def _safe_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"_payload": str(payload)}
    p = dict(payload)
    if "auth" in p:
        p["auth"] = "***"
    return p


async def _read_response_body(resp: aiohttp.ClientResponse) -> Any:
    try:
        return await resp.json(content_type=None)
    except Exception:
        try:
            return await resp.text()
        except Exception:
            return "<unreadable response body>"


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

    async def post(self, method: str, payload: Dict[str, Any], *, trace_id: str) -> Dict[str, Any]:
        if not self.base:
            return {"success": False, "error": "BITRIX24_WEBHOOK_URL is empty"}
        if not self.session:
            raise RuntimeError("BitrixWebhookClient session is not initialized")

        url = f"{self.base}/{method}"
        t0 = time.perf_counter()

        if _dbg():
            logger.warning(
                "[%s] Bitrix webhook POST %s payload=%s base=%s",
                trace_id,
                method,
                _truncate(_safe_json(_safe_payload(payload)), _dbg_limit()),
                _mask_webhook_url(self.base),
            )

        try:
            async with self.session.post(url, json=payload) as resp:
                data = await _read_response_body(resp)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)

                if _dbg():
                    logger.warning(
                        "[%s] Bitrix webhook RESP %s status=%s ms=%s body=%s",
                        trace_id,
                        method,
                        resp.status,
                        elapsed_ms,
                        _truncate(_safe_json(data), _dbg_limit()),
                    )

        except Exception as e:
            logger.exception("[%s] Bitrix webhook request failed: %s %s", trace_id, method, e)
            return {"success": False, "error": f"Request failed: {e}"}

        if isinstance(data, dict) and data.get("error"):
            logger.error("[%s] Bitrix webhook error (%s): %s", trace_id, method, data)
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

    async def post(self, method: str, payload: Dict[str, Any], *, trace_id: str) -> Dict[str, Any]:
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

        t0 = time.perf_counter()

        if _dbg():
            logger.warning(
                "[%s] Bitrix oauth POST %s url=%s payload=%s base=%s",
                trace_id,
                method,
                url,
                _truncate(_safe_json(_safe_payload(body)), _dbg_limit()),
                base,
            )

        try:
            async with self.session.post(url, json=body) as resp:
                data = await _read_response_body(resp)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)

                if _dbg():
                    logger.warning(
                        "[%s] Bitrix oauth RESP %s status=%s ms=%s body=%s",
                        trace_id,
                        method,
                        resp.status,
                        elapsed_ms,
                        _truncate(_safe_json(data), _dbg_limit()),
                    )

        except Exception as e:
            logger.exception("[%s] Bitrix OAuth request failed: %s %s", trace_id, method, e)
            return {"success": False, "error": f"Request failed: {e}"}

        if isinstance(data, dict) and data.get("error"):
            logger.error("[%s] Bitrix OAuth error (%s): %s", trace_id, method, data)
            return {
                "success": False,
                "error": data.get("error"),
                "error_description": data.get("error_description"),
                "raw": data,
            }

        return {"success": True, "result": data.get("result") if isinstance(data, dict) else data}


async def _post_bitrix(method: str, payload: Dict[str, Any], *, trace_id: Optional[str] = None) -> Dict[str, Any]:
    tid = trace_id or uuid.uuid4().hex[:12]

    if _dbg():
        logger.warning("[%s] Bitrix call: method=%s base=%s", tid, method, _safe_base_info())

    if _use_oauth():
        oauth = BitrixOAuthService()
        async with BitrixOAuthRestClient(_portal(), oauth) as bx:
            return await bx.post(method, payload, trace_id=tid)

    async with BitrixWebhookClient(_webhook_url()) as bx:
        return await bx.post(method, payload, trace_id=tid)


async def ensure_event_bound(*, event_name: str, handler_url: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Идемпотентно гарантирует подписку на событие.
    Управляет "Bitrix -> наш endpoint" (например OnImConnectorMessageAdd).
    Учитывает, что event.get может вернуть dict ИЛИ list.
    """
    tid = trace_id or uuid.uuid4().hex[:12]

    if not _is_enabled():
        return {"success": False, "error": "BITRIX24_ENABLED=false"}

    if not _use_oauth():
        return {"success": False, "error": "BITRIX24_USE_OAUTH=false (events require OAuth app context)"}

    handler_url = (handler_url or "").strip()
    if not handler_url:
        return {"success": False, "error": "handler_url is empty"}

    res = await _post_bitrix("event.get", {}, trace_id=tid)
    if not res.get("success"):
        return res

    raw = res.get("result")

    existing_handlers = []

    # 🔥 Главное исправление
    if isinstance(raw, dict):
        existing = raw.get(event_name)
        if isinstance(existing, str):
            existing_handlers = [existing]
        elif isinstance(existing, list):
            existing_handlers = [str(x) for x in existing]
        elif existing:
            existing_handlers = [str(existing)]

    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            en = (
                item.get("eventName")
                or item.get("EVENT_NAME")
                or item.get("event_name")
                or item.get("EVENT")
            )
            hd = (
                item.get("handler")
                or item.get("HANDLER")
                or item.get("handler_url")
                or item.get("HANDLER_URL")
            )
            if str(en or "").strip() == event_name and hd:
                existing_handlers.append(str(hd))

    if any(h.rstrip("/") == handler_url.rstrip("/") for h in existing_handlers):
        logger.info("[%s] event already bound: %s -> %s", tid, event_name, handler_url)
        return {"success": True, "bound": True, "already": True}

    bind_payload = {"EVENT_NAME": event_name, "HANDLER": handler_url}
    bind_res = await _post_bitrix("event.bind", bind_payload, trace_id=tid)
    if not bind_res.get("success"):
        return bind_res

    logger.info("[%s] event bound: %s -> %s", tid, event_name, handler_url)
    return {"success": True, "bound": True, "already": False, "raw": bind_res.get("result")}


async def ensure_connector_ready(*, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Идемпотентная проверка/доведение до готовности:
      - проверяем imopenlines.config.list (для удобства диагностики)
      - проверяем imconnector.status для (CONNECTOR, LINE)
      - если статус плохой -> imconnector.register -> imconnector.activate -> повторная проверка
    """
    tid = trace_id or uuid.uuid4().hex[:12]

    if not _is_enabled():
        return {"success": False, "error": "BITRIX24_ENABLED=false"}
    if not _use_oauth():
        return {"success": False, "error": "BITRIX24_USE_OAUTH=false (connector setup requires OAuth)"}

    connector = _openlines_connector_id()
    line = _openlines_line_id()
    base = _public_base_url()

    if not connector:
        return {"success": False, "error": "BITRIX24_CONNECTOR_ID is empty"}
    if not line:
        return {"success": False, "error": "BITRIX24_OPENLINE_ID is empty"}
    if not base:
        return {"success": False, "error": "PUBLIC_BASE_URL is empty (required for register placement handler)"}

    steps: Dict[str, Any] = {"connector": connector, "line": line, "base": base, "steps": []}

    try:
        ol = await _post_bitrix("imopenlines.config.list", {"select": ["ID", "NAME", "ACTIVE"]}, trace_id=tid)
        steps["steps"].append({"imopenlines.config.list": ol})
    except Exception as e:
        steps["steps"].append({"imopenlines.config.list": {"success": False, "error": str(e)}})

    status = await _post_bitrix("imconnector.status", {"CONNECTOR": connector, "LINE": line}, trace_id=tid)
    steps["steps"].append({"imconnector.status": status})

    need_register = False
    need_activate = False

    if not status.get("success"):
        need_register = True
        need_activate = True
    else:
        st = status.get("result") or {}
        if isinstance(st, dict) and st.get("ACTIVE") in ("N", "n", False, 0, "0", None, ""):
            need_activate = True

    if need_register:
        reg_payload = {
            "ID": connector,
            "NAME": _connector_name(),
            "PLACEMENT_HANDLER": f"{base}/bitrix/install",
        }
        reg = await _post_bitrix("imconnector.register", reg_payload, trace_id=tid)
        steps["steps"].append({"imconnector.register": reg})

    if need_activate:
        act_payload = {
            "CONNECTOR": connector,
            "LINE": line,
            "ACTIVE": "Y",
        }
        act = await _post_bitrix("imconnector.activate", act_payload, trace_id=tid)
        steps["steps"].append({"imconnector.activate": act})

    status2 = await _post_bitrix("imconnector.status", {"CONNECTOR": connector, "LINE": line}, trace_id=tid)
    steps["steps"].append({"imconnector.status.after": status2})

    ok = bool(status2.get("success"))
    return {"success": ok, "details": steps}


async def ensure_bitrix_ready(*, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Полная идемпотентная подготовка для двусторонних чатов:
      1) ensure_connector_ready()
      2) ensure_event_bound(OnImConnectorMessageAdd -> /bitrix/events)
    """
    tid = trace_id or uuid.uuid4().hex[:12]

    if not _is_enabled():
        return {"success": False, "error": "BITRIX24_ENABLED=false"}

    base = _public_base_url()
    if not base:
        return {"success": False, "error": "PUBLIC_BASE_URL is empty"}

    handler = f"{base}/bitrix/events"

    conn = await ensure_connector_ready(trace_id=tid)
    ev = await ensure_event_bound(event_name="OnImConnectorMessageAdd", handler_url=handler, trace_id=tid)

    return {"success": bool(conn.get("success") and ev.get("success")), "connector": conn, "event": ev}


async def ensure_bitrix_lead(lead_obj: Any, fields: Dict[str, Any], *, trace_id: Optional[str] = None) -> Dict[str, Any]:
    tid = trace_id or uuid.uuid4().hex[:12]

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

    if _dbg():
        logger.warning(
            "[%s] ensure_bitrix_lead: has_lead_id=%s lead_id=%s fields=%s",
            tid,
            bool(bitrix_lead_id),
            bitrix_lead_id,
            _truncate(_safe_json(fields), _dbg_limit()),
        )

    if bitrix_lead_id:
        payload = {"id": int(bitrix_lead_id), "fields": fields}
        res = await _post_bitrix("crm.lead.update", payload, trace_id=tid)
        if res.get("success"):
            return {"success": True, "lead_id": int(bitrix_lead_id), "created": False}
        return res

    payload = {"fields": fields}
    res = await _post_bitrix("crm.lead.add", payload, trace_id=tid)
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
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    tid = trace_id or uuid.uuid4().hex[:12]

    if not _is_enabled():
        return {"success": False, "error": "BITRIX24_ENABLED=false"}

    if not _use_oauth() and not _webhook_url():
        return {"success": False, "error": "BITRIX24_WEBHOOK_URL is empty (webhook mode)"}
    if _use_oauth() and not _portal():
        return {"success": False, "error": "BITRIX24_PORTAL is empty (oauth mode)"}

    line_raw = _openlines_line_id()
    if not line_raw:
        return {"success": False, "error": "BITRIX24_OPENLINE_ID (LINE) is empty"}

    try:
        line = int(line_raw)
    except ValueError:
        return {"success": False, "error": f"Invalid LINE value: {line_raw}"}

    connector = _openlines_connector_id()
    if not connector:
        return {"success": False, "error": "BITRIX24_CONNECTOR_ID (CONNECTOR) is empty"}

    user_display = f"@{tg_username}" if tg_username else f"Telegram {tg_user_id}"

    msg: Dict[str, Any] = {
        "user": {
            "id": str(tg_user_id),
            "name": user_display,
            "url": f"https://t.me/{tg_username}" if tg_username else f"https://t.me/{tg_user_id}",
        },
        "chat": {
            "id": str(tg_user_id),
            "name": f"Telegram {tg_user_id}",
        },
        "message": {
            "id": str(message_id),
            "date": int(unix_date),
            "text": text,
        },
    }

    if int(lead_id) > 0:
        msg["crm"] = {"lead": int(lead_id)}

    payload = {
        "CONNECTOR": connector,
        "LINE": line,
        "MESSAGES": [msg],
    }

    logger.warning(
        "[%s] OpenLines send: connector=%s line=%s tg_user_id=%s msg_id=%s lead_id=%s",
        tid,
        connector,
        line,
        tg_user_id,
        message_id,
        lead_id,
    )

    res = await _post_bitrix("imconnector.send.messages", payload, trace_id=tid)

    if not res.get("success"):
        logger.warning(
            "[%s] OpenLines HTTP-level failure: %s",
            tid,
            _truncate(_safe_json(res.get("raw") or res), _dbg_limit()),
        )
        return res

    inner = res.get("result") or {}
    data = inner.get("DATA") or {}
    results = data.get("RESULT") or []

    if results and isinstance(results, list):
        first = results[0]
        if not first.get("SUCCESS"):
            logger.error(
                "[%s] OpenLines rejected message: %s",
                tid,
                _truncate(_safe_json(first), _dbg_limit()),
            )
            return {
                "success": False,
                "error": "IMCONNECTOR_MESSAGE_FAILED",
                "raw": first,
            }

    logger.warning("[%s] OpenLines send OK", tid)
    return {"success": True}
