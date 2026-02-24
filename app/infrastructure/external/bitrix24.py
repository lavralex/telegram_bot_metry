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
        try:
            oauth = BitrixOAuthService()
            async with BitrixOAuthRestClient(_portal(), oauth) as bx:
                return await bx.post(method, payload, trace_id=tid)
        except Exception as e:
            logger.exception("[%s] Bitrix OAuth call failed: %s %s", tid, method, e)
            return {"success": False, "error": str(e)}

    try:
        async with BitrixWebhookClient(_webhook_url()) as bx:
            return await bx.post(method, payload, trace_id=tid)
    except Exception as e:
        logger.exception("[%s] Bitrix webhook call failed: %s %s", tid, method, e)
        return {"success": False, "error": str(e)}


async def ensure_event_bound(*, event_name: str, handler_url: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Идемпотентно гарантирует подписку на событие.
    Управляет "Bitrix -> наш endpoint" (например OnImConnectorMessageAdd).
    """
    tid = trace_id or uuid.uuid4().hex[:12]

    if not _is_enabled():
        return {"success": False, "error": "BITRIX24_ENABLED=false"}

    if not _use_oauth():
        return {"success": False, "error": "BITRIX24_USE_OAUTH=false (events require OAuth app context)"}

    handler_url = (handler_url or "").strip()
    if not handler_url:
        return {"success": False, "error": "handler_url is empty"}

    def _handlers_from_event_get_result(current: Any) -> list[str]:
        handlers: list[str] = []
        if isinstance(current, dict):
            existing = current.get(event_name)
            if isinstance(existing, str):
                handlers = [existing]
            elif isinstance(existing, list):
                handlers = [str(x) for x in existing]
            elif existing is None:
                handlers = []
            else:
                handlers = [str(existing)]
        elif isinstance(current, list):
            # Some Bitrix portals return event.get as a list of bindings.
            for item in current:
                if not isinstance(item, dict):
                    continue
                ev = str(item.get("EVENT") or item.get("event") or "").strip()
                if ev != event_name:
                    continue
                handler = item.get("HANDLER") or item.get("handler")
                if handler:
                    handlers.append(str(handler))
        return handlers

    res = await _post_bitrix("event.get", {}, trace_id=tid)
    if not res.get("success"):
        return res

    existing_handlers = _handlers_from_event_get_result(res.get("result"))

    if any(h.rstrip("/") == handler_url.rstrip("/") for h in existing_handlers):
        logger.info("[%s] event already bound: %s -> %s", tid, event_name, handler_url)
        return {"success": True, "bound": True, "already": True}

    bind_payload = {"EVENT": event_name, "HANDLER": handler_url}
    bind_res = await _post_bitrix("event.bind", bind_payload, trace_id=tid)
    if not bind_res.get("success"):
        err = str(bind_res.get("error") or "")
        desc = str(bind_res.get("error_description") or "")
        if err == "ERROR_CORE" and "already binded" in desc.lower():
            # Defensive re-check: some portals return "already binded" even when bound to another URL.
            recheck = await _post_bitrix("event.get", {}, trace_id=tid + "c")
            if recheck.get("success"):
                checked_handlers = _handlers_from_event_get_result(recheck.get("result"))
                if any(h.rstrip("/") == handler_url.rstrip("/") for h in checked_handlers):
                    logger.info("[%s] event already bound (bind conflict): %s -> %s", tid, event_name, handler_url)
                    return {"success": True, "bound": True, "already": True, "raw": bind_res.get("raw")}
                return {
                    "success": False,
                    "error": "EVENT_BINDED_TO_OTHER_HANDLER",
                    "error_description": f"{event_name} is already bound, but not to {handler_url}",
                    "raw": recheck.get("result"),
                }
            return recheck
        return bind_res

    logger.info("[%s] event bound: %s -> %s", tid, event_name, handler_url)
    return {"success": True, "bound": True, "already": False, "raw": bind_res.get("result")}


async def ensure_connector_ready(*, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Идемпотентная проверка/доведение до готовности:
      - проверяем imopenlines.config.list (для удобства диагностики)
      - проверяем imconnector.status для (CONNECTOR, LINE)
      - если статус плохой -> imconnector.register -> imconnector.activate -> повторная проверка

    Важное ограничение: некоторые порталы всё равно могут требовать включить канал в UI.
    Но тогда status покажет причину — и ты будешь видеть её в логах и /bitrix/diag.
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

    app_info = await _post_bitrix("app.info", {}, trace_id=tid)
    conn = await ensure_connector_ready(trace_id=tid)
    ev = await ensure_event_bound(event_name="OnImConnectorMessageAdd", handler_url=handler, trace_id=tid)

    return {
        "success": bool(app_info.get("success") and conn.get("success") and ev.get("success")),
        "app_info": app_info,
        "connector": conn,
        "event": ev,
    }


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
            "url": f"https://t.me/{tg_username}" if tg_username else "",
        },
        "message": {
            "id": str(message_id),
            "date": int(unix_date),
            "text": text,
        },
    }

    if int(lead_id) > 0:
        msg["crm"] = {"lead": int(lead_id)}
        # Some Bitrix portals/connectors expect crm_entity format for binding.
        msg["crm_entity"] = f"L_{int(lead_id)}"

    payload: Dict[str, Any] = {
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

    inner = res.get("result")

    # Bitrix may return heterogeneous response shapes for this endpoint.
    # Consider only explicit success markers as success; everything else is treated as a failure.
    if isinstance(inner, bool):
        if inner is True:
            logger.warning("[%s] OpenLines send OK (bool result)", tid)
            return {"success": True}
        logger.error("[%s] OpenLines rejected message: result=false", tid)
        return {"success": False, "error": "IMCONNECTOR_MESSAGE_FAILED", "raw": res}

    if isinstance(inner, dict):
        data = inner.get("DATA") or {}
        results = data.get("RESULT") or []

        if isinstance(results, list) and results:
            first = results[0] if isinstance(results[0], dict) else {"raw": results[0]}
            if first.get("SUCCESS") is True:
                logger.warning("[%s] OpenLines send OK (DATA.RESULT)", tid)
                return {"success": True}

            logger.error(
                "[%s] OpenLines rejected message: %s",
                tid,
                _truncate(_safe_json(first), _dbg_limit()),
            )

            # Compatibility retry: some portals reject crm_entity with generic "missing required data".
            errs = first.get("ERRORS") or []
            has_missing_data = any("не все необходимые данные" in str(e).lower() for e in errs)
            if has_missing_data and "crm_entity" in msg:
                msg2 = dict(msg)
                msg2.pop("crm_entity", None)
                payload2 = dict(payload)
                payload2["MESSAGES"] = [msg2]
                logger.warning("[%s] OpenLines retry without crm_entity", tid)
                retry_res = await _post_bitrix("imconnector.send.messages", payload2, trace_id=tid + "r")
                if retry_res.get("success"):
                    retry_inner = retry_res.get("result")
                    if isinstance(retry_inner, bool) and retry_inner is True:
                        logger.warning("[%s] OpenLines send OK on retry (bool result)", tid)
                        return {"success": True}
                    if isinstance(retry_inner, dict):
                        retry_data = retry_inner.get("DATA") or {}
                        retry_results = retry_data.get("RESULT") or []
                        if isinstance(retry_results, list) and retry_results:
                            r0 = retry_results[0] if isinstance(retry_results[0], dict) else {"raw": retry_results[0]}
                            if r0.get("SUCCESS") is True:
                                logger.warning("[%s] OpenLines send OK on retry (DATA.RESULT)", tid)
                                return {"success": True}
                        if retry_inner.get("SUCCESS") is True:
                            logger.warning("[%s] OpenLines send OK on retry (SUCCESS)", tid)
                            return {"success": True}

            return {
                "success": False,
                "error": "IMCONNECTOR_MESSAGE_FAILED",
                "raw": first,
            }

        if inner.get("SUCCESS") is True:
            logger.warning("[%s] OpenLines send OK (SUCCESS)", tid)
            return {"success": True}

        if "SUCCESS" in inner and inner.get("SUCCESS") is not True:
            logger.error("[%s] OpenLines rejected message: %s", tid, _truncate(_safe_json(inner), _dbg_limit()))
            return {"success": False, "error": "IMCONNECTOR_MESSAGE_FAILED", "raw": inner}

    logger.error("[%s] OpenLines unknown response shape: %s", tid, _truncate(_safe_json(res), _dbg_limit()))
    return {"success": False, "error": "IMCONNECTOR_UNEXPECTED_RESPONSE", "raw": res}
