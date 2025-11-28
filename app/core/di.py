from .config import config

# Простой контейнер зависимостей
dependencies = {
    'config': config,
    # Потом добавим: 'db', 'lead_service', etc.
}

def get_dependency(name: str):
    return dependencies.get(name)