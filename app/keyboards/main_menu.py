from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Недвижимость для инвестиций", callback_data="invest")],
            [InlineKeyboardButton(text="Недвижимость для жизни", callback_data="living")],
            [InlineKeyboardButton(text="Связаться с менеджером", callback_data="manager")],
            [InlineKeyboardButton(text="Аналитика доходности локаций", callback_data="analytics")],
            [InlineKeyboardButton(text="Подписаться на Telegram-канал", url="https://t.me/metrigroup")]
        ]
    )