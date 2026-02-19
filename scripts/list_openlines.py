import asyncio
from app.infrastructure.external.bitrix24 import _post_bitrix

async def main():
    res = await _post_bitrix("imopenlines.config.list", {})
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
