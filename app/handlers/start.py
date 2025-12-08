from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
import logging

logger = logging.getLogger(__name__)

start_router = Router()

@start_router.message(Command("help"))
async def help_command(message: Message):
    """Команда помощи"""
    help_text = (
        "🤖 **ПОМОЩЬ**\n\n"
        "Я помогу вам:\n"
        "• Подобрать недвижимость для инвестиций\n"
        "• Найти жилье для жизни\n"
        "• Связать вас с менеджером\n"
        "• Предоставить аналитику доходности\n\n"
        "Просто нажмите кнопку меню внизу!\n\n"
        "💡 *Для начала работы отправьте /start*"
    )
    
    await message.answer(help_text)

@start_router.message(Command("about"))
async def about_command(message: Message):
    """Информация о боте"""
    about_text = (
        "🏢 **ГК МЕТРЫ**\n\n"
        "Ведущая компания на рынке недвижимости\n\n"
        "📞 Контакты:\n"
        "Телефон: +7 (495) 123-45-67\n"
        "Email: info@metry.group\n"
        "Сайт: https://metry.group\n\n"
        "📍 Адрес:\n"
        "Москва, ул. Примерная, д. 123\n\n"
        "🕒 Часы работы:\n"
        "Пн-Пт: 9:00-20:00\n"
        "Сб-Вс: 10:00-18:00"
    )
    
    await message.answer(about_text)

# Можно добавить другие общие команды