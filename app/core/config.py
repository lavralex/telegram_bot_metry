from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int | None = None) -> int | None:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


# ---- env file loading ----
ENV = os.getenv("ENV", "development")
env_file = f".env.{ENV}"
if Path(env_file).exists():
    load_dotenv(env_file)
else:
    load_dotenv()


class Config:
    # -------- Core --------
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []
    ENV = ENV

    DEV_MODE = _env_bool("DEV_MODE", False)
    ENABLE_ADMIN_CHAT = _env_bool("ENABLE_ADMIN_CHAT", True)
    AUTO_MIGRATE = _env_bool("AUTO_MIGRATE", True)

    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://bot_user:secure_password@localhost:5432/telegram_bot")

    # -------- Bitrix (common toggle) --------
    BITRIX24_ENABLED = _env_bool("BITRIX24_ENABLED", False)

    # -------- Bitrix OAuth mode --------
    BITRIX24_USE_OAUTH = _env_bool("BITRIX24_USE_OAUTH", False)
    BITRIX24_PORTAL = (os.getenv("BITRIX24_PORTAL", "") or "").strip()  # e.g. xxxxx.bitrix24.ru
    BITRIX24_CLIENT_ID = (os.getenv("BITRIX24_CLIENT_ID", "") or "").strip()
    BITRIX24_CLIENT_SECRET = (os.getenv("BITRIX24_CLIENT_SECRET", "") or "").strip()
    BITRIX24_REDIRECT_URI = (os.getenv("BITRIX24_REDIRECT_URI", "") or "").strip()

    # -------- Bitrix Webhook mode (fallback) --------
    # Format: https://xxxxx.bitrix24.ru/rest/1/<token>
    BITRIX24_WEBHOOK_URL = (os.getenv("BITRIX24_WEBHOOK_URL", "") or "").rstrip("/")

    # -------- CRM Lead SOURCE_ID (optional, for marking leads as TG source) --------
    BITRIX24_TELEGRAM_SOURCE_ID = (os.getenv("BITRIX24_TELEGRAM_SOURCE_ID", "") or "").strip()

    # -------- OpenLines --------
    BITRIX24_OPENLINES_ENABLED = _env_bool("BITRIX24_OPENLINES_ENABLED", True)

    # For imconnector.send.messages:
    # CONNECTOR = connector code (e.g. telegram_bot)
    BITRIX24_CONNECTOR_ID = (os.getenv("BITRIX24_CONNECTOR_ID", "") or "").strip()

    # LINE = OpenLine ID (usually small number: 1,2,5...)
    BITRIX24_OPENLINE_ID = (os.getenv("BITRIX24_OPENLINE_ID", "") or "").strip()

    # -------- UTM --------
    UTM_SEGMENTS = {
        "utm_elit": "Элитная недвижимость",
        "utm_apart": "Апартаменты",
        "utm_realestate": "Недвижимость",
        "utm_agents": "Агенты",
        "utm_banks": "Банки",
        "utm_finance": "Финансы",
        "utm_invest": "Инвестиции",
        "utm_blogs": "Блоги об инвестициях и недвижимости",
        "utm_sublease": "Субаренда",
        "utm_old_nedviga": "Старая недвижимость",
        "utm_old_apart": "Старые апартаменты",
        "utm_old_elite": "Старая элитная недвижимость",
    }

    # -------- Paths --------
    @property
    def base_dir(self) -> Path:
        return Path(__file__).parent.parent.parent

    @property
    def media_path(self) -> Path:
        return self.base_dir / "media"

    @property
    def logs_path(self) -> Path:
        return self.base_dir / "logs"

    @property
    def management_image_path(self) -> Path:
        return self.media_path / "UpravCom.png"

    @property
    def subscribe_image_path(self) -> Path:
        return self.media_path / "sub.png"

    @property
    def analytics_pdf_path(self) -> Path:
        return self.media_path / "Аналитика доходности ГК МЕТРЫ.pdf"

    @property
    def investor_portfolio_path(self) -> Path:
        return self.media_path / "Портфель инвестора.pdf"

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    # -------- Validation --------
    @classmethod
    def validate(cls) -> None:
        required_vars = ["BOT_TOKEN"]
        missing = [var for var in required_vars if not getattr(cls, var)]
        if missing:
            raise ValueError(f"Отсутствуют обязательные переменные: {', '.join(missing)}")

        if cls.BITRIX24_ENABLED:
            # Auth mode validation
            if cls.BITRIX24_USE_OAUTH:
                if not cls.BITRIX24_PORTAL:
                    raise ValueError("BITRIX24_ENABLED=true + OAUTH, но BITRIX24_PORTAL пустой")
                if not cls.BITRIX24_CLIENT_ID or not cls.BITRIX24_CLIENT_SECRET:
                    raise ValueError("BITRIX24_ENABLED=true + OAUTH, но нет BITRIX24_CLIENT_ID/SECRET")
            else:
                if not cls.BITRIX24_WEBHOOK_URL:
                    raise ValueError("BITRIX24_ENABLED=true (webhook), но BITRIX24_WEBHOOK_URL пустой")

            # OpenLines validation (only if enabled)
            if cls.BITRIX24_OPENLINES_ENABLED:
                if not cls.BITRIX24_CONNECTOR_ID:
                    raise ValueError("OpenLines включены, но BITRIX24_CONNECTOR_ID пустой")
                if not cls.BITRIX24_OPENLINE_ID:
                    raise ValueError("OpenLines включены, но BITRIX24_OPENLINE_ID пустой")

        config_instance = cls()
        config_instance.media_path.mkdir(exist_ok=True)
        config_instance.logs_path.mkdir(exist_ok=True)


config = Config()
config.validate()
