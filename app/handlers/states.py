from aiogram.fsm.state import State, StatesGroup

class InvestmentStates(StatesGroup):
    waiting_for_budget = State()
    waiting_for_timeline = State()
    waiting_for_management = State()

class LivingStates(StatesGroup):
    waiting_for_budget = State()
    waiting_for_timeline = State()

class ManagerStates(StatesGroup):
    waiting_for_experience = State()

class AnalyticsStates(StatesGroup):
    waiting_for_contact = State()

class CommonStates(StatesGroup):
    waiting_for_contact = State()