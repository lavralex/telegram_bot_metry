import asyncio
from app.infrastructure.external.bitrix24 import _post_bitrix

async def main():
    res = await _post_bitrix(
        "imconnector.activate",
        {
            "CONNECTOR": "telegram_bot",
            "LINE": "133",
            "ACTIVE": "Y",
        },
    )
    print(res)

asyncio.run(main())

