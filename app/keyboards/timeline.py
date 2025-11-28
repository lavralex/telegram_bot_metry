from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_timeline_keyboard(segment: str = None):
    buttons = [
        [InlineKeyboardButton(text="В течение 3-х месяцев", callback_data="timeline_3months")],
        [InlineKeyboardButton(text="В течение года", callback_data="timeline_1year")],
        [InlineKeyboardButton(text="Не планирую в этом году", callback_data="timeline_no_plan")],
    ]
    
    # Динамическая кнопка назад
    back_data = "back_to_budget"
    if segment == "investment":
        back_data = "back_to_budget_investment"
    elif segment == "living":
        back_data = "back_to_budget_living"
        
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back_data)])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)