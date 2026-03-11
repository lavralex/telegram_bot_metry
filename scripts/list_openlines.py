import asyncio
import os
import sys
from pathlib import Path


def _bootstrap_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        load_dotenv = None

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    env = os.getenv("ENV", "development")
    if load_dotenv:
        load_dotenv(root / ".env", override=False)
        load_dotenv(root / f".env.{env}", override=True)
    os.environ.setdefault("BOT_TOKEN", "script_dummy_token")


_bootstrap_env()

from app.infrastructure.external.bitrix24 import _post_bitrix

async def main():
    res = await _post_bitrix("imopenlines.config.list", {})
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
