import asyncio
import base64
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

from app.core.config import config
from app.infrastructure.external.bitrix24 import _post_bitrix


ICON_PATH = Path("media/sub.png")

async def main():
    connector_id = config.BITRIX24_CONNECTOR_ID
    if not connector_id:
        raise RuntimeError("BITRIX24_CONNECTOR_ID пуст")

    payload = {
        "ID": connector_id,
        "NAME": "Metri Telegram Bot",
        "PLACEMENT_HANDLER": f"{config.PUBLIC_BASE_URL}/bitrix/install",
    }

    if ICON_PATH.exists():
        raw = ICON_PATH.read_bytes()
        b64 = base64.b64encode(raw).decode("utf-8")
        payload["ICON"] = {"DATA_IMAGE": f"data:image/png;base64,{b64}"}

    res = await _post_bitrix("imconnector.register", payload)
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
