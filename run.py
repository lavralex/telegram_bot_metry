#!/usr/bin/env python3
"""
Скрипт для запуска бота с автоматической миграцией
"""

import subprocess
import sys
import os

def run_alembic_migration():
    """Запускает миграции Alembic"""
    print("🔄 Проверка миграций Alembic...")
    
    try:
        # Проверяем наличие миграций
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print("⚠️ Ошибка при проверке миграций:")
            print(result.stderr)
            return False
        
        print("✅ Миграции Alembic настроены")
        return True
        
    except FileNotFoundError:
        print("❌ Alembic не найден. Установите: pip install alembic")
        return False

def create_auto_migration():
    """Создает автоматическую миграцию"""
    print("🔄 Создание автоматической миграции...")
    
    try:
        # Создаем новую миграцию
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", "Auto migration"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Миграция создана")
            
            # Применяем миграцию
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                print("✅ Миграция применена")
                return True
            else:
                print("❌ Ошибка применения миграции:")
                print(result.stderr)
                return False
        else:
            print("❌ Ошибка создания миграции:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

def run_bot():
    """Запускает бота"""
    print("🚀 Запуск бота...")
    
    try:
        # Импортируем и запускаем main
        from app.main import main
        import asyncio
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот завершил работу")
    except Exception as e:
        print(f"❌ Ошибка запуска бота: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 TELEGRAM BOT LAUNCHER")
    print("=" * 50)
    
    # Проверяем наличие .env файла
    if not os.path.exists(".env") and not os.path.exists(".env.development"):
        print("⚠️ Внимание: .env файл не найден")
        print("Создайте .env файл из .env.example")
    
    # Проверяем миграции
    if run_alembic_migration():
        # Если миграции настроены, запускаем бота
        run_bot()
    else:
        print("⚠️ Попытка автоматического создания таблиц...")
        # Запускаем бота, который сам создаст таблицы
        run_bot()