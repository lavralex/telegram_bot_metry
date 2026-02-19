from __future__ import annotations

import logging
from aiohttp import web
from typing import Optional, Any, Dict, List

logger = logging.getLogger(__name__)


def _extract_user_id_from_chat_id(chat_id: Any) -> Optional[int]:
    """
    Ожидаем chat_id вида:
      - "tg_123456"
      - "123456"
      - 123456

    ВАЖНО: мы в send_message_to_openlines используем chat.id = str(tg_user_id),
    поэтому здесь поддерживаем и чисто цифровые chat_id.
    """
    if isinstance(chat_id, int):
        return chat_id

    if isinstance(chat_id, str):
        if chat_id.startswith("tg_"):
            tail = chat_id[3:]
            if tail.isdigit():
                return int(tail)
        if chat_id.isdigit():
            return int(chat_id)

    return None


def _is_from_telegram_connector(msg: Dict[str, Any]) -> bool:

    connector = msg.get("connector") or msg.get("CONNECTOR")
    if connector and str(connector).lower() != "telegram":
        return False
    return True


async def _safe_json(request: web.Request) -> Dict[str, Any]:
    try:
        return await request.json()
    except Exception:
        try:
            post = await request.post()
            if post:
                data = dict(post)
                return {"_form": data}
        except Exception:
            pass

        try:
            raw = await request.text()
            logger.warning("Bitrix event: non-JSON body: %r", raw[:800])
        except Exception:
            pass
        return {}


def _extract_messages(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = payload.get("data") or {}
    msgs = data.get("MESSAGES") or data.get("messages") or []
    if isinstance(msgs, list):
        return msgs
    return []


def _extract_text(msg: Dict[str, Any]) -> str:
    m = msg.get("message") or {}
    return (m.get("text") or m.get("TEXT") or "").strip()


def _extract_chat_id(msg: Dict[str, Any]) -> Any:
    chat = msg.get("chat") or {}
    return chat.get("id") or chat.get("ID")


def _extract_author(msg: Dict[str, Any]) -> Dict[str, Any]:
    user = msg.get("user") or {}
    author_id = user.get("id") or user.get("ID")
    author_name = user.get("name") or user.get("NAME") or ""
    sender = msg.get("sender") or msg.get("author") or {}
    sender_id = sender.get("id") or sender.get("ID")
    sender_name = sender.get("name") or sender.get("NAME")

    return {
        "author_id": author_id or sender_id,
        "author_name": author_name or sender_name or "",
    }


def build_app(bot):
    app = web.Application()

    async def bitrix_events(request: web.Request):
        payload = await _safe_json(request)

        logger.info("[BITRIX EVENT] incoming: %s", str(payload)[:1200])

        event = payload.get("event")
        if event != "OnImConnectorMessageAdd":
            return web.json_response({"ok": True, "ignored": True})

        messages = _extract_messages(payload)
        if not messages:
            return web.json_response({"ok": True, "empty": True})
        sent = 0
        skipped = 0
        errors = 0

        for msg in messages:
            try:
                if not _is_from_telegram_connector(msg):
                    skipped += 1
                    continue

                chat_id = _extract_chat_id(msg)
                text = _extract_text(msg)
                if not text:
                    skipped += 1
                    continue

                user_id = _extract_user_id_from_chat_id(chat_id)
                if not user_id:
                    skipped += 1
                    logger.warning("Не смогли определить user_id из chat_id=%r", chat_id)
                    continue

                author = _extract_author(msg)
                author_name = author.get("author_name") or "Менеджер"
                out_text = f"💬 {author_name}: {text}"

                logger.info("[BITRIX EVENT] -> TG user_id=%s text=%r", user_id, out_text[:300])
                await bot.send_message(user_id, out_text)
                sent += 1

            except Exception as e:
                errors += 1
                logger.error("Ошибка обработки/отправки в TG: %s", e, exc_info=True)

        return web.json_response(
            {
                "ok": True,
                "sent": sent,
                "skipped": skipped,
                "errors": errors,
            }
        )

    app.router.add_post("/bitrix/events", bitrix_events)
    return app


async def start_bitrix_events_server(bot, host: str = "0.0.0.0", port: int = 8080) -> web.AppRunner:
    app = build_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("✅ Bitrix events server started on http://%s:%s/bitrix/events", host, port)
    return runner
