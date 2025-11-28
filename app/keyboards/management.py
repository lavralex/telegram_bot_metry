from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_management_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сам(а)", callback_data="management_self")],
            [InlineKeyboardButton(text="Через УК", callback_data="management_company")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_timeline_investment")]
        ]
    )