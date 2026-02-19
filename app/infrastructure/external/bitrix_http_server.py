from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import config
from app.infrastructure.external.bitrix_oauth import BitrixOAuthService, OAuthToken, OAUTH_TOKEN_URL

import aiohttp
import json

logger = logging.getLogger(__name__)


def _extract_user_id_from_chat_id(chat_id):
    if isinstance(chat_id, int):
        return chat_id
    if isinstance(chat_id, str):
        if chat_id.startswith("tg_") and chat_id[3:].isdigit():
            return int(chat_id[3:])
        if chat_id.isdigit():
            return int(chat_id)
    return None


def _extract_messages(payload: dict):
    data = payload.get("data") or {}
    msgs = data.get("MESSAGES") or data.get("messages") or []
    return msgs if isinstance(msgs, list) else []


def _extract_text(msg: dict) -> str:
    m = msg.get("message") or {}
    return (m.get("text") or m.get("TEXT") or "").strip()


def _extract_chat_id(msg: dict):
    chat = msg.get("chat") or {}
    return chat.get("id") or chat.get("ID")


def _extract_author_name(msg: dict) -> str:
    user = msg.get("user") or {}
    name = user.get("name") or user.get("NAME")
    if name:
        return str(name)

    sender = msg.get("sender") or msg.get("author") or {}
    name = sender.get("name") or sender.get("NAME")
    return str(name) if name else "Менеджер"


def create_app(bot) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"ok": True}

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

        logger.info("[BITRIX INSTALL] %s", str(payload)[:1500])

        return {"ok": True}

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
            logger.error("OAuth token exchange bad response: %s", str(data)[:1200])
            return JSONResponse({"ok": False, "error": "bad_token_response", "raw": data}, status_code=500)

        expires_in = int(data.get("expires_in", 3600))
        token = OAuthToken(
            access_token=str(data["access_token"]),
            refresh_token=str(data.get("refresh_token", "")),
            expires_at=BitrixOAuthService._now_utc() + timedelta(seconds=expires_in),
        )

        oauth = BitrixOAuthService()
        oauth.storage.save(token)

        logger.info("✅ OAuth tokens saved. expires_in=%s", expires_in)

        return {"ok": True, "saved": True}

    @app.post("/bitrix/events")
    async def bitrix_events(request: Request):
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            try:
                raw = (await request.body()).decode("utf-8", errors="ignore").strip()

                if raw.startswith("'") and raw.endswith("'"):
                    raw = raw[1:-1].strip()

                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {}

        logger.info("[BITRIX EVENT] incoming: %s", str(payload)[:1000])

        event = (
            payload.get("event")
            or payload.get("EVENT")
            or (payload.get("data") or {}).get("event")
            or (payload.get("data") or {}).get("EVENT")
        )
        event = (str(event) if event is not None else "").strip()

        if event.lower() != "onimconnectormessageadd":
            return {"ok": True, "ignored": True}

        messages = _extract_messages(payload)
        if not messages:
            return {"ok": True, "empty": True}

        sent = skipped = errors = 0

        for msg in messages:
            try:
                text = _extract_text(msg)
                if not text:
                    skipped += 1
                    continue

                chat_id = _extract_chat_id(msg)
                user_id = _extract_user_id_from_chat_id(chat_id)
                if not user_id:
                    skipped += 1
                    continue

                author = _extract_author_name(msg)
                out_text = f"💬 {author}: {text}"

                await bot.send_message(user_id, out_text)
                sent += 1

            except Exception as e:
                errors += 1
                logger.error("Bitrix event -> TG failed: %s", e, exc_info=True)

        return {"ok": True, "sent": sent, "skipped": skipped, "errors": errors}

    return app
