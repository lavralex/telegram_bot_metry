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


ENV = os.getenv("ENV", "development")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_env_file = _PROJECT_ROOT / f".env.{ENV}"
_default_env = _PROJECT_ROOT / ".env"

if _default_env.exists():
    load_dotenv(_default_env, override=False)
if _env_file.exists():
    load_dotenv(_env_file, override=True)


class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []
    ENV = ENV

    DEV_MODE = _env_bool("DEV_MODE", False)
    ENABLE_ADMIN_CHAT = _env_bool("ENABLE_ADMIN_CHAT", True)
    AUTO_MIGRATE = _env_bool("AUTO_MIGRATE", True)

    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://bot_user:secure_password@localhost:5432/telegram_bot")

    BITRIX24_ENABLED = _env_bool("BITRIX24_ENABLED", False)

    BITRIX24_USE_OAUTH = _env_bool("BITRIX24_USE_OAUTH", False)
    BITRIX24_PORTAL = (os.getenv("BITRIX24_PORTAL_URL") or os.getenv("BITRIX24_PORTAL", "") or "").strip()
    BITRIX24_CLIENT_ID = (os.getenv("BITRIX24_OAUTH_CLIENT_ID") or os.getenv("BITRIX24_CLIENT_ID", "") or "").strip()
    BITRIX24_CLIENT_SECRET = (
        os.getenv("BITRIX24_OAUTH_CLIENT_SECRET") or os.getenv("BITRIX24_CLIENT_SECRET", "") or ""
    ).strip()
    PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL", "") or "").rstrip("/")
    BITRIX24_REDIRECT_URI = (
        os.getenv("BITRIX24_OAUTH_REDIRECT_URI") or os.getenv("BITRIX24_REDIRECT_URI", "") or ""
    ).strip()
    BITRIX24_OAUTH_ACCESS_TOKEN = (os.getenv("BITRIX24_OAUTH_ACCESS_TOKEN", "") or "").strip()
    BITRIX24_OAUTH_REFRESH_TOKEN = (os.getenv("BITRIX24_OAUTH_REFRESH_TOKEN", "") or "").strip()
    BITRIX24_OAUTH_TOKEN_URL = (
        os.getenv("BITRIX24_OAUTH_TOKEN_URL", "https://oauth.bitrix.info/oauth/token/") or ""
    ).strip()
    BITRIX24_OAUTH_EXPIRES_IN = _env_int("BITRIX24_OAUTH_EXPIRES_IN", 3600) or 3600

    BITRIX24_WEBHOOK_URL = (os.getenv("BITRIX24_WEBHOOK_URL", "") or "").rstrip("/")

    BITRIX24_TELEGRAM_SOURCE_ID = (os.getenv("BITRIX24_TELEGRAM_SOURCE_ID", "") or "").strip()

    BITRIX24_OPENLINES_ENABLED = _env_bool("BITRIX24_OPENLINES_ENABLED", True)

    BITRIX24_CONNECTOR_ID = (os.getenv("BITRIX24_CONNECTOR_ID", "") or "").strip()
    BITRIX24_OPENLINE_ID = (os.getenv("BITRIX24_OPENLINE_ID", "") or "").strip()

    BITRIX24_DEBUG = _env_bool("BITRIX24_DEBUG", False)
    BITRIX24_DEBUG_HTTP_BODY_LIMIT = _env_int("BITRIX24_DEBUG_HTTP_BODY_LIMIT", 4000) or 4000

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

    @classmethod
    def validate(cls) -> None:
        required_vars = ["BOT_TOKEN"]
        missing = [var for var in required_vars if not getattr(cls, var)]
        if missing:
            raise ValueError(f"Отсутствуют обязательные переменные: {', '.join(missing)}")

        if cls.BITRIX24_ENABLED:
            if cls.BITRIX24_USE_OAUTH:
                if not cls.BITRIX24_PORTAL:
                    raise ValueError("BITRIX24_ENABLED=true + OAUTH, но BITRIX24_PORTAL пустой")
                if not cls.BITRIX24_CLIENT_ID or not cls.BITRIX24_CLIENT_SECRET:
                    raise ValueError("BITRIX24_ENABLED=true + OAUTH, но нет BITRIX24_CLIENT_ID/SECRET")
            else:
                if not cls.BITRIX24_WEBHOOK_URL:
                    raise ValueError("BITRIX24_ENABLED=true (webhook), но BITRIX24_WEBHOOK_URL пустой")

            if cls.BITRIX24_OPENLINES_ENABLED:
                if not cls.BITRIX24_CONNECTOR_ID:
                    raise ValueError("OpenLines включены, но BITRIX24_CONNECTOR_ID пустой")
                if not cls.BITRIX24_OPENLINE_ID:
                    raise ValueError("OpenLines включены, но BITRIX24_OPENLINE_ID пустой")

        if cls.is_production:
            cls.BITRIX24_DEBUG = False

        config_instance = cls()
        config_instance.media_path.mkdir(exist_ok=True)
        config_instance.logs_path.mkdir(exist_ok=True)


config = Config()
config.validate()
