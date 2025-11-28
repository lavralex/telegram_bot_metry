from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="недвижимость для инвестиций", callback_data="invest")],
            [InlineKeyboardButton(text="недвижимость для жизни", callback_data="living")],
            [InlineKeyboardButton(text="связаться с менеджером", callback_data="manager")],
            [InlineKeyboardButton(text="аналитика доходности локаций", callback_data="analytics")],
            [InlineKeyboardButton(text="подписаться на Telegram-канал", url="https://t.me/metrigroup")]
        ]
    )