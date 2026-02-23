import logging
import os
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from app.core.config import config


def _mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _truthy(v: str) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on", "enable", "enabled"}


def _bitrix_log_mode() -> str:
    """
    BITRIX24_LOG:
      - "" / "0" / "off" / "false" -> disabled
      - "1" / "on" / "true" / "info" -> bitrix.log (INFO+)
      - "debug" -> bitrix.log (INFO+) + bitrix_debug.log (DEBUG)
    """
    v = str(getattr(config, "BITRIX24_LOG", "") or os.getenv("BITRIX24_LOG", "")).strip().lower()
    if not v or v in {"0", "off", "false", "no", "n", "disabled", "disable"}:
        return "off"
    if v == "debug":
        return "debug"
    if v == "info":
        return "info"
    if _truthy(v):
        return "info"
    return "info"


def setup_logging():
    """
    Логи:
      - logs/bot.log (основной)
      - logs/bitrix.log (INFO+) — если BITRIX24_LOG включён
      - logs/bitrix_debug.log (DEBUG) — если BITRIX24_LOG=debug

    Важно: директория берётся из config.logs_path (base_dir/logs), а не из текущей рабочей папки.
    """
    log_dir = Path(getattr(config, "logs_path", Path("logs")))
    _mkdir(log_dir)

    detailed_formatter = logging.Formatter(
        "%(asctime)s | %(name)-40s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    simple_formatter = logging.Formatter("%(levelname)-8s | %(message)s")

    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Root level
    if config.is_production:
        root_logger.setLevel(logging.INFO)
    else:
        root_logger.setLevel(logging.DEBUG)

    main_file_handler = RotatingFileHandler(
        log_dir / "bot.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    main_file_handler.setFormatter(detailed_formatter)
    main_file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    if config.is_production:
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
    else:
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(detailed_formatter)

    root_logger.addHandler(main_file_handler)
    root_logger.addHandler(console_handler)

    for lib in ["aiogram", "sqlalchemy", "aiohttp", "asyncio", "uvicorn"]:
        logging.getLogger(lib).setLevel(logging.WARNING)

    # --- Bitrix dedicated logs controlled by ONE env var: BITRIX24_LOG ---
    mode = _bitrix_log_mode()
    if mode != "off":
        bitrix_info_handler = RotatingFileHandler(
            log_dir / "bitrix.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        bitrix_info_handler.setFormatter(detailed_formatter)
        bitrix_info_handler.setLevel(logging.INFO)

        bitrix_logger_names = [
            "app.infrastructure.external.bitrix24",
            "app.infrastructure.external.bitrix_oauth",
            "app.infrastructure.external.bitrix_http_server",
        ]
        for name in bitrix_logger_names:
            lg = logging.getLogger(name)
            lg.addHandler(bitrix_info_handler)
            lg.propagate = True

        if mode == "debug":
            bitrix_debug_handler = RotatingFileHandler(
                log_dir / "bitrix_debug.log",
                maxBytes=20 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            bitrix_debug_handler.setFormatter(detailed_formatter)
            bitrix_debug_handler.setLevel(logging.DEBUG)

            for name in bitrix_logger_names:
                lg = logging.getLogger(name)
                lg.setLevel(logging.DEBUG)
                lg.addHandler(bitrix_debug_handler)
                lg.propagate = True

            uv_err = logging.getLogger("uvicorn.error")
            uv_err.addHandler(bitrix_debug_handler)
            uv_err.propagate = True

    return root_logger
