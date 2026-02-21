import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from app.core.config import config


def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    detailed_formatter = logging.Formatter(
        '%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    simple_formatter = logging.Formatter(
        '%(levelname)-8s | %(message)s'
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    if config.is_production:
        root_logger.setLevel(logging.INFO)
    else:
        root_logger.setLevel(logging.DEBUG)

    main_file_handler = RotatingFileHandler(
        log_dir / "bot.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
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

    libraries = ['aiogram', 'sqlalchemy', 'aiohttp', 'asyncio']
    for lib in libraries:
        logging.getLogger(lib).setLevel(logging.WARNING)

    business_logger = logging.getLogger('bot.business')
    business_logger.setLevel(logging.INFO)

    if getattr(config, "BITRIX24_DEBUG", False) and not config.is_production:
        bitrix_file_handler = RotatingFileHandler(
            log_dir / "bitrix_debug.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8'
        )
        bitrix_file_handler.setFormatter(detailed_formatter)
        bitrix_file_handler.setLevel(logging.DEBUG)

        bitrix_logger_names = [
            "app.infrastructure.external.bitrix24",
            "app.infrastructure.external.bitrix_oauth",
            "bot.messages",
        ]

        for name in bitrix_logger_names:
            logger = logging.getLogger(name)
            logger.setLevel(logging.DEBUG)
            logger.addHandler(bitrix_file_handler)
            logger.propagate = True

    return root_logger