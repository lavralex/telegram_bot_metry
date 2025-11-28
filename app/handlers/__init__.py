from .start import start_router
from .investment import investment_router
from .living import living_router
from .manager import manager_router
from .analytics import analytics_router
from .back import back_router
from .contact import contact_router
from .budget import budget_router
from .timeline import timeline_router
from .admin import admin_router

__all__ = [
    'start_router',
    'investment_router',
    'living_router', 
    'manager_router',
    'analytics_router',
    'back_router',
    'contact_router',
    'budget_router',
    'timeline_router',
    'admin_router'
]