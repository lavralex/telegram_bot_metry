from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_budget_keyboard(segment: str = None):
    buttons = [
        [InlineKeyboardButton(text="6-10 млн", callback_data="budget_6-10")],
        [InlineKeyboardButton(text="10-20 млн", callback_data="budget_10-20")],
        [InlineKeyboardButton(text="20-30 млн", callback_data="budget_20-30")],
        [InlineKeyboardButton(text="30+ млн", callback_data="budget_30plus")],
    ]

    back_data = "back_to_main"
    if segment == "investment":
        back_data = "back_to_main"
    elif segment == "living":
        back_data = "back_to_main"
        
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back_data)])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)