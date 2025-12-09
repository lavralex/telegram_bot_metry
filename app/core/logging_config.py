import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from app.core.config import config

def setup_logging():
    """Профессиональная настройка логирования"""
    
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    detailed_formatter = logging.Formatter(
        '%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '%(levelname)-8s | %(message)s'
    )

    logger = logging.getLogger()

    file_handler = RotatingFileHandler(
        log_dir / "bot.log",
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(detailed_formatter)
    file_handler.setLevel(logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    
    if config.is_production:
        logger.setLevel(logging.INFO)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
    else:
        logger.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    libraries = ['aiogram', 'sqlalchemy', 'aiohttp', 'asyncio']
    for lib in libraries:
        logging.getLogger(lib).setLevel(logging.WARNING)
    
    business_logger = logging.getLogger('bot.business')
    business_logger.setLevel(logging.INFO)
    
    return logger