# scripts/register_connector.py
import asyncio
import base64
from pathlib import Path

from app.core.config import config
from app.infrastructure.external.bitrix24 import _post_bitrix  # да, "внутренний" импорт, для разового скрипта ок

# Положи любую svg/png иконку, либо оставь ICON пустым
ICON_PATH = Path("media/sub.png")  # поменяй на существующий файл, или закомментируй ICON

async def main():
    connector_id = config.BITRIX24_CONNECTOR_ID  # важно: должно совпадать с тем, что ты шлёшь в send.messages
    if not connector_id:
        raise RuntimeError("BITRIX24_CONNECTOR_ID пуст")

    payload = {
        "ID": connector_id,
        "NAME": "Metri Telegram Bot",
        # Куда Bitrix будет ходить, когда нажмут "Подключить" в Contact Center
        "PLACEMENT_HANDLER": f"{config.PUBLIC_BASE_URL}/bitrix/install",
    }

    if ICON_PATH.exists():
        raw = ICON_PATH.read_bytes()
        b64 = base64.b64encode(raw).decode("utf-8")
        # если это png:
        payload["ICON"] = {"DATA_IMAGE": f"data:image/png;base64,{b64}"}

    res = await _post_bitrix("imconnector.register", payload)
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
