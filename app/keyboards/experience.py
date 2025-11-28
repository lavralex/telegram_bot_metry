from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_experience_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Уже инвестировал(а)", callback_data="experience_invested")],
            [InlineKeyboardButton(text="Нет, я новый клиент", callback_data="experience_new")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
        ]
    )