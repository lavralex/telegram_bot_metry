import logging
from typing import Dict, Any

from app.core.config import config
from app.infrastructure.external.bitrix24 import _post_bitrix, ensure_event_bound

logger = logging.getLogger(__name__)


async def ensure_connector_ready() -> Dict[str, Any]:
    """
    Полный авто-bootstrap:
    - проверка коннектора на линии
    - регистрация (если нужно)
    - активация
    - подписка на события
    """

    connector = config.BITRIX24_CONNECTOR_ID
    line = config.BITRIX24_OPENLINE_ID
    base = config.PUBLIC_BASE_URL.rstrip("/")
    handler = f"{base}/bitrix/events"

    if not connector or not line:
        return {"success": False, "error": "CONNECTOR or LINE missing in config"}

    result: Dict[str, Any] = {"steps": []}

    status = await _post_bitrix(
        "imconnector.status",
        {
            "CONNECTOR": connector,
            "LINE": line,
        },
    )

    result["steps"].append({"status_check": status})

    need_register = False
    need_activate = False

    if not status.get("success"):
        need_register = True
        need_activate = True
    else:
        st = status.get("result") or {}
        if not st or not st.get("ACTIVE"):
            need_activate = True

    if need_register:
        register = await _post_bitrix(
            "imconnector.register",
            {
                "ID": connector,
                "NAME": "Metri Telegram Bot",
                "PLACEMENT_HANDLER": f"{base}/bitrix/install",
            },
        )
        result["steps"].append({"register": register})

    if need_activate:
        activate = await _post_bitrix(
            "imconnector.activate",
            {
                "CONNECTOR": connector,
                "LINE": line,
                "ACTIVE": "Y",
            },
        )
        result["steps"].append({"activate": activate})

    event = await ensure_event_bound(
        event_name="OnImConnectorMessageAdd",
        handler_url=handler,
    )
    result["steps"].append({"event_bind": event})

    logger.info("Bitrix bootstrap result: %s", result)
    return {"success": True, "details": result}
