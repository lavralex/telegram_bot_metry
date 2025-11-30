from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_policy_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Политика обработки персональных данных", url="https://metry.group/policy/")]
        ]
    )

def get_subscribe_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться на Telegram-канал", url="https://t.me/metrigroup")]
        ]
    )