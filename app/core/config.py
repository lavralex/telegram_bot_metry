import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем правильный .env файл
ENV = os.getenv('ENV', 'development')
env_file = f'.env.{ENV}'
if Path(env_file).exists():
    load_dotenv(env_file)
else:
    load_dotenv()

class Config:
    # Основные настройки
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(','))) if os.getenv("ADMIN_IDS") else []
    ENV = ENV
    
    # 👇 ОБНОВЛЯЕМ: PostgreSQL вместо SQLite
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://bot_user:secure_password@localhost:5432/telegram_bot")
    
    # Bitrix24
    BITRIX24_WEBHOOK_URL = os.getenv("BITRIX24_WEBHOOK_URL", "")
    BITRIX24_ENABLED = os.getenv("BITRIX24_ENABLED", "false").lower() == "true"
    
    # UTM сегменты
    UTM_SEGMENTS = {
        "utm_elit": "Элитная недвижимость",
        "utm_apart": "Апартаменты",
        "utm_realestate": "Недвижимость", 
        "utm_agents": "Агенты",
        "utm_banks": "Банки",
        "utm_finance": "Финансы",
        "utm_invest": "Инвестиции",
        "utm_blogs": "Блоги об инвестициях и недвижимости",
        "utm_sublease": "Субаренда"
    }
    
    # Пути (для медиафайлов все равно нужны)
    @property
    def base_dir(self):
        return Path(__file__).parent.parent.parent
    
    @property
    def media_path(self):
        return self.base_dir / "media"
    
    @property
    def logs_path(self):
        return self.base_dir / "logs"
    
    @property
    def management_image_path(self):
        return self.media_path / "UpravCom.png"
    
    @property
    def subscribe_image_path(self):
        return self.media_path / "sub.png"
    
    @property
    def analytics_pdf_path(self):
        return self.media_path / "Аналитика доходности ГК МЕТРЫ.pdf"
    
    @property
    def is_production(self):
        return self.ENV == "production"
    
    @classmethod
    def validate(cls):
        required_vars = ['BOT_TOKEN']
        missing = [var for var in required_vars if not getattr(cls, var)]
        if missing:
            raise ValueError(f"Отсутствуют обязательные переменные: {', '.join(missing)}")
        
        # Создаем необходимые директории для медиа и логов
        config_instance = cls()
        config_instance.media_path.mkdir(exist_ok=True)
        config_instance.logs_path.mkdir(exist_ok=True)

config = Config()
config.validate()