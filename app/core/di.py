from .config import config

dependencies = {
    'config': config,
}

def get_dependency(name: str):
    return dependencies.get(name)