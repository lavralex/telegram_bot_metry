from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import config
from app.infrastructure.external.bitrix_oauth import BitrixOAuthService, OAUTH_TOKEN_URL
from app.infrastructure.external.bitrix24 import send_openlines_delivery_status

logger = logging.getLogger(__name__)

_DEDUP_TTL_SEC = 600
_processed: Dict[str, float] = {}
_TEXT_DEDUP_TTL_SEC = 90
_recent_texts: Dict[str, float] = {}


def _now() -> float:
    return time.time()


def _dedup_gc() -> None:
    t = _now()
    for k, ts in list(_processed.items()):
        if (t - ts) >= _DEDUP_TTL_SEC:
            _processed.pop(k, None)
    for k, ts in list(_recent_texts.items()):
        if (t - ts) >= _TEXT_DEDUP_TTL_SEC:
            _recent_texts.pop(k, None)


def _dedup_key(msg: Dict[str, Any]) -> Optional[str]:
    m = msg.get("message") or {}
    mid = m.get("id") or m.get("ID")
    if not mid:
        return None
    chat = msg.get("chat") or {}
    cid = chat.get("id") or chat.get("ID") or ""
    return f"{cid}:{mid}"


def _dedup_seen(key: str) -> bool:
    ts = _processed.get(key)
    if ts is None:
        return False
    return (_now() - ts) < _DEDUP_TTL_SEC


def _dedup_mark(key: str) -> None:
    _processed[key] = _now()


def _text_dedup_key(*, user_id: int, text: str) -> str:
    norm = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return f"{int(user_id)}:{norm}"


def _text_dedup_seen(key: str) -> bool:
    ts = _recent_texts.get(key)
    if ts is None:
        return False
    return (_now() - ts) < _TEXT_DEDUP_TTL_SEC


def _text_dedup_mark(key: str) -> None:
    _recent_texts[key] = _now()


def _expected_connector() -> str:
    return (str(getattr(config, "BITRIX24_CONNECTOR_ID", "") or "") or "telegram_bot").strip().lower()


def _is_from_our_connector(msg: Dict[str, Any], expected: str) -> bool:
    connector = msg.get("connector") or msg.get("CONNECTOR")
    if not connector:
        return True
    return str(connector).strip().lower() == expected


def _extract_user_id_from_chat_id(chat_id: Any) -> Optional[int]:
    if isinstance(chat_id, int):
        return chat_id
    if not isinstance(chat_id, str):
        return None

    s = chat_id.strip()
    m = re.match(r"^tg_u(\d+)_l\d+$", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None

    m = re.match(r"^tg_u(\d+)_s.+$", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None

    m = re.match(r"^tg_(\d+)_lead_\d+$", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None

    if s.startswith("tg_") and s[3:].isdigit():
        return int(s[3:])
    if s.isdigit():
        return int(s)

    m = re.search(r"(\d{5,})\s*$", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None

    return None


def _extract_messages(payload: dict) -> List[Dict[str, Any]]:
    candidates: List[Any] = []

    data = payload.get("data")
    if data is not None:
        candidates.append(data)

    data_u = payload.get("DATA")
    if data_u is not None:
        candidates.append(data_u)

    for c in candidates:
        if isinstance(c, list):
            return [x for x in c if isinstance(x, dict)]
        if isinstance(c, dict):
            msgs = c.get("MESSAGES") or c.get("messages")
            if isinstance(msgs, list):
                return [x for x in msgs if isinstance(x, dict)]

    return []


def _extract_text(msg: dict) -> str:
    m = msg.get("message") or {}
    return (m.get("text") or m.get("TEXT") or "").strip()


def _extract_chat_id(msg: dict) -> Any:
    chat = msg.get("chat") or {}
    return chat.get("id") or chat.get("ID")


def _extract_author_name(msg: dict) -> str:
    user = msg.get("user") or {}
    name = user.get("name") or user.get("NAME")
    if name:
        return str(name)

    sender = msg.get("sender") or msg.get("author") or {}
    name = sender.get("name") or sender.get("NAME")
    return str(name) if name else "Manager"


def _normalize_bitrix_text(text: str) -> str:
    # Bitrix often sends simple BBCode markers in OpenLines payload.
    t = (text or "").replace("[br]", "\n").replace("[BR]", "\n")
    t = re.sub(r"\[/?(?:b|i|u|s|quote|code)\]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _extract_manager_name_from_bbcode(text: str) -> tuple[str | None, str]:
    raw = text or ""
    m = re.match(r"^\s*\[b\]\s*(.*?)\s*\[/b\]\s*(?:\[br\]|\n)\s*(.*)$", raw, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None, _normalize_bitrix_text(raw)
    manager_name = (m.group(1) or "").strip()
    body = _normalize_bitrix_text(m.group(2) or "")
    return (manager_name or None), body


def _normalize_manager_header_name(name: str) -> str:
    n = str(name or "").strip()
    n = re.sub(r"\s+", " ", n)
    n = n.rstrip(":").strip()

    # Avoid "Manager Manager" and similar duplicate prefixes.
    n = re.sub(r"^(manager)\s+\1\b", r"\1", n, flags=re.IGNORECASE)
    n = re.sub(r"^(?:manager|менеджер)\s+(?=manager\b|менеджер\b)", "", n, flags=re.IGNORECASE)

    # If name already starts with "Manager", keep only the rest for header composition.
    n = re.sub(r"^(?:manager|менеджер)\s+", "", n, flags=re.IGNORECASE).strip()
    if not n:
        return "Manager"
    return n


async def _send_to_tg(
    bot,
    user_id: int,
    out_text: str,
    trace: str,
    *,
    connector: str = "",
    line: int = 0,
    im_chat_id: str = "",
    im_message_id: str = "",
) -> None:
    try:
        await bot.send_message(user_id, out_text)
        logger.info("[%s] [BITRIX->TG] sent user_id=%s len=%s", trace, user_id, len(out_text))
        if connector and line and im_chat_id and im_message_id:
            await send_openlines_delivery_status(
                connector=connector,
                line=line,
                im_chat_id=im_chat_id,
                im_message_id=im_message_id,
                trace_id=trace + "D",
            )
    except Exception as e:
        logger.error("[%s] [BITRIX->TG] send failed user_id=%s err=%s", trace, user_id, e, exc_info=True)


def _try_json_loads(s: str) -> dict:
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _split_bracket_key(key: str) -> List[str]:
    parts: List[str] = []
    cur = ""
    i = 0
    while i < len(key):
        ch = key[i]
        if ch == "[":
            if cur:
                parts.append(cur)
                cur = ""
            j = key.find("]", i + 1)
            if j == -1:
                break
            parts.append(key[i + 1 : j])
            i = j + 1
            continue
        cur += ch
        i += 1
    if cur:
        parts.append(cur)
    return [p for p in parts if p != ""]


def _safe_install_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for k, v in (payload or {}).items():
        kl = str(k or "").lower()
        if "access_token" in kl or "refresh_token" in kl or "application_token" in kl:
            safe[k] = "***"
        else:
            safe[k] = v
    return safe


def _extract_install_auth(payload: Dict[str, Any]) -> Dict[str, Any]:
    auth = payload.get("auth")
    if isinstance(auth, dict):
        return auth

    # Common ONAPPINSTALL form shape: auth[access_token], auth[refresh_token], ...
    out: Dict[str, Any] = {}
    for k, v in (payload or {}).items():
        ks = str(k or "")
        if ks.startswith("auth[") and ks.endswith("]"):
            out[ks[5:-1]] = v
    return out


def _inflate_bracket_form(flat: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts keys like data[MESSAGES][0][message][text] into nested dict/list.
    """
    root: Dict[str, Any] = {}

    def _ensure_list_size(lst: List[Any], idx: int) -> None:
        while len(lst) <= idx:
            lst.append(None)

    for k, v in flat.items():
        if "[" not in k or "]" not in k:
            continue
        path = _split_bracket_key(k)
        if not path:
            continue

        cur: Any = root
        for i, part in enumerate(path):
            last = i == len(path) - 1
            next_part = path[i + 1] if not last else None
            is_index = part.isdigit()

            if is_index:
                idx = int(part)
                if not isinstance(cur, list):
                    break
                _ensure_list_size(cur, idx)
                if last:
                    cur[idx] = v
                else:
                    child = cur[idx]
                    if child is None:
                        child = [] if (next_part and next_part.isdigit()) else {}
                        cur[idx] = child
                    cur = child
                continue

            if not isinstance(cur, dict):
                break

            if last:
                cur[part] = v
            else:
                child = cur.get(part)
                if child is None:
                    child = [] if (next_part and next_part.isdigit()) else {}
                    cur[part] = child
                cur = child

    return root


async def _parse_bitrix_event_payload(request: Request) -> Dict[str, Any]:
    ct = (request.headers.get("content-type") or "").lower()

    if "application/json" in ct:
        try:
            p = await request.json()
            return p if isinstance(p, dict) else {}
        except Exception:
            return {}

    if "application/x-www-form-urlencoded" in ct or "multipart/form-data" in ct:
        try:
            form = await request.form()
            data: Dict[str, Any] = dict(form)

            raw_data = data.get("data") or data.get("DATA")
            if isinstance(raw_data, str):
                inner = _try_json_loads(raw_data)
                if inner:
                    data["data"] = inner

            inflated = _inflate_bracket_form(data)
            if inflated:
                # Merge parsed nested structure without losing original flat keys.
                for kk, vv in inflated.items():
                    if kk not in data:
                        data[kk] = vv

            return data
        except Exception:
            return {}

    try:
        raw = (await request.body()).decode("utf-8", errors="ignore").strip()
        if not raw:
            return {}

        if "=" in raw and "&" in raw and not raw.lstrip().startswith("{"):
            parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
            flat = {k: (v[0] if isinstance(v, list) and v else "") for k, v in parsed.items()}
            raw_data = flat.get("data") or flat.get("DATA")
            if isinstance(raw_data, str):
                inner = _try_json_loads(raw_data)
                if inner:
                    flat["data"] = inner
            return flat

        p = _try_json_loads(raw)
        return p if p else {}
    except Exception:
        return {}


def create_app(bot) -> FastAPI:
    app = FastAPI()
    expected_connector = _expected_connector()

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/bitrix/diag")
    async def bitrix_diag():
        try:
            from app.infrastructure.external.bitrix24 import _post_bitrix

            oauth = BitrixOAuthService()
            res_event = await _post_bitrix("event.get", {})
            res_status = await _post_bitrix(
                "imconnector.status",
                {"CONNECTOR": getattr(config, "BITRIX24_CONNECTOR_ID", ""), "LINE": getattr(config, "BITRIX24_OPENLINE_ID", "")},
            )

            return {
                "ok": True,
                "oauth_token_state": oauth.get_token_state(),
                "event_get": res_event,
                "imconnector_status": res_status,
                "hint": "call /bitrix/diag after OAuth install to see bindings",
                "ensure_ready_example": "POST /bitrix/ensure-ready",
            }
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/bitrix/ensure-ready")
    async def bitrix_ensure_ready():
        try:
            from app.infrastructure.external.bitrix24 import ensure_bitrix_ready

            res = await ensure_bitrix_ready()
            return {"ok": True, "result": res}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.api_route("/bitrix/install", methods=["GET", "POST"])
    async def bitrix_install(request: Request):
        payload = {}
        try:
            if request.method == "POST":
                ct = (request.headers.get("content-type") or "").lower()
                if "application/json" in ct:
                    payload = await request.json()
                else:
                    form = await request.form()
                    payload = dict(form)
            else:
                payload = dict(request.query_params)
        except Exception:
            payload = {"_raw": "failed_to_parse"}

        logger.info("[BITRIX INSTALL] %s", str(_safe_install_payload(payload))[:1000])

        # For local Bitrix apps, ONAPPINSTALL carries OAuth tokens in auth[*].
        auth = _extract_install_auth(payload)
        access_token = str(auth.get("access_token") or "").strip()
        refresh_token = str(auth.get("refresh_token") or "").strip()
        expires_in_raw = auth.get("expires_in", 3600)
        try:
            expires_in = int(expires_in_raw or 3600)
        except Exception:
            expires_in = 3600

        saved = False
        bootstrap: Dict[str, Any] = {"success": False, "error": "skipped"}

        if access_token and refresh_token:
            try:
                oauth = BitrixOAuthService()
                oauth.save_oauth_tokens(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=expires_in,
                )
                saved = True
                logger.info("OAuth tokens saved from /bitrix/install. expires_in=%s", expires_in)
            except Exception as e:
                logger.error("Failed to save OAuth tokens from /bitrix/install: %s", e, exc_info=True)
                return JSONResponse({"ok": False, "error": "save_tokens_failed", "details": str(e)}, status_code=500)

            try:
                from app.infrastructure.external.bitrix24 import ensure_bitrix_ready

                bootstrap = await ensure_bitrix_ready()
                logger.info("Bitrix bootstrap after install: %s", str(bootstrap)[:1200])
            except Exception as e:
                logger.error("ensure_bitrix_ready after install failed: %s", e, exc_info=True)
                bootstrap = {"success": False, "error": str(e)}

        return {
            "ok": True,
            "event": str(payload.get("event") or payload.get("EVENT") or ""),
            "saved": saved,
            "bootstrap": bootstrap,
        }

    @app.get("/bitrix/oauth/callback")
    async def bitrix_oauth_callback(request: Request, code: str | None = None, state: str | None = None):
        if not code:
            return JSONResponse({"ok": False, "error": "missing_code"}, status_code=400)

        if not config.BITRIX24_CLIENT_ID or not config.BITRIX24_CLIENT_SECRET:
            return JSONResponse({"ok": False, "error": "missing_client_id_or_secret"}, status_code=500)

        payload = {
            "grant_type": "authorization_code",
            "client_id": config.BITRIX24_CLIENT_ID,
            "client_secret": config.BITRIX24_CLIENT_SECRET,
            "code": code,
        }

        redirect_uri = getattr(config, "BITRIX24_REDIRECT_URI", "") or ""
        if redirect_uri:
            payload["redirect_uri"] = redirect_uri

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(OAUTH_TOKEN_URL, data=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    data = await resp.json(content_type=None)
        except Exception as e:
            logger.exception("OAuth token exchange failed: %s", e)
            return JSONResponse({"ok": False, "error": "token_exchange_failed", "details": str(e)}, status_code=500)

        if not isinstance(data, dict) or "access_token" not in data:
            logger.error("OAuth token exchange bad response: %s", str(data)[:800])
            return JSONResponse({"ok": False, "error": "bad_token_response", "raw": data}, status_code=500)

        expires_in = int(data.get("expires_in", 3600))
        oauth = BitrixOAuthService()
        oauth.save_oauth_tokens(
            access_token=str(data["access_token"]),
            refresh_token=str(data.get("refresh_token", "")),
            expires_in=expires_in,
        )

        logger.info("OAuth tokens saved to dedicated storage. expires_in=%s", expires_in)

        try:
            from app.infrastructure.external.bitrix24 import ensure_bitrix_ready

            res = await ensure_bitrix_ready()
            logger.info("Bitrix bootstrap after callback: %s", str(res)[:1200])
        except Exception as e:
            logger.error("ensure_bitrix_ready failed: %s", e, exc_info=True)
            res = {"success": False, "error": str(e)}

        return {"ok": True, "saved": True, "bootstrap": res}

    @app.api_route("/bitrix/events", methods=["GET", "POST"])
    async def bitrix_events(request: Request):
        if request.method == "GET":
            return PlainTextResponse("OK", status_code=200)

        trace = request.headers.get("X-Request-Id") or os.urandom(6).hex()
        payload: Dict[str, Any] = await _parse_bitrix_event_payload(request)

        event = (
            payload.get("event")
            or payload.get("EVENT")
            or (payload.get("data") or {}).get("event")
            or (payload.get("data") or {}).get("EVENT")
        )
        event = (str(event) if event is not None else "").strip()

        logger.warning(
            "[%s] [BITRIX EVENT] ct=%s event=%s keys=%s",
            trace,
            (request.headers.get("content-type") or ""),
            event,
            list(payload.keys())[:25],
        )

        if event.lower() != "onimconnectormessageadd":
            return PlainTextResponse("OK", status_code=200)

        messages = _extract_messages(payload)
        if not messages:
            logger.warning(
                "[%s] [BITRIX EVENT] no messages extracted; keys=%s",
                trace,
                list(payload.keys())[:50],
            )
            return PlainTextResponse("OK", status_code=200)

        _dedup_gc()

        for msg in messages:
            try:
                logger.warning(
                    "[%s] [BITRIX EVENT] msg extracted keys=%s",
                    trace,
                    list(msg.keys())[:20] if isinstance(msg, dict) else type(msg).__name__,
                )

                if not _is_from_our_connector(msg, expected_connector):
                    logger.warning("[%s] [BITRIX EVENT] skip foreign connector", trace)
                    continue

                key = _dedup_key(msg)
                if key and _dedup_seen(key):
                    logger.info("[%s] [BITRIX EVENT] dedup skip key=%s", trace, key)
                    continue

                raw_text = _extract_text(msg)
                if not raw_text:
                    logger.warning("[%s] [BITRIX EVENT] empty text in message", trace)
                    continue

                chat_id = _extract_chat_id(msg)
                user_id = _extract_user_id_from_chat_id(chat_id)
                if not user_id:
                    logger.warning("[%s] Cannot map chat_id=%r -> tg user_id", trace, chat_id)
                    continue

                author = _extract_author_name(msg)
                manager_name, clean_text = _extract_manager_name_from_bbcode(raw_text)
                if not clean_text:
                    logger.warning("[%s] [BITRIX EVENT] empty text after normalize", trace)
                    continue

                header_name = _normalize_manager_header_name(manager_name or author)
                if header_name.lower() == "manager":
                    out_text = f"Manager:\n\n{clean_text}"
                else:
                    out_text = f"Manager {header_name}:\n\n{clean_text}"

                tkey = _text_dedup_key(user_id=user_id, text=out_text)
                if _text_dedup_seen(tkey):
                    logger.info("[%s] [BITRIX EVENT] text dedup skip user_id=%s", trace, user_id)
                    continue

                data_root = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                connector = str(
                    msg.get("connector")
                    or msg.get("CONNECTOR")
                    or data_root.get("CONNECTOR")
                    or data_root.get("connector")
                    or ""
                ).strip()
                line_raw = (
                    msg.get("line")
                    or msg.get("LINE")
                    or data_root.get("LINE")
                    or data_root.get("line")
                    or 0
                )
                try:
                    line = int(line_raw)
                except Exception:
                    line = 0
                im_obj = msg.get("im") if isinstance(msg.get("im"), dict) else {}
                im_chat_id = str(im_obj.get("chat_id") or "").strip()
                im_message_id = str(im_obj.get("message_id") or "").strip()

                if key:
                    _dedup_mark(key)
                _text_dedup_mark(tkey)

                asyncio.create_task(
                    _send_to_tg(
                        bot,
                        user_id,
                        out_text,
                        trace,
                        connector=connector,
                        line=line,
                        im_chat_id=im_chat_id,
                        im_message_id=im_message_id,
                    )
                )

            except Exception as e:
                logger.error("[%s] Bitrix event processing failed: %s", trace, e, exc_info=True)

        return PlainTextResponse("OK", status_code=200)

    return app
