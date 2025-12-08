#!/usr/bin/env python3
"""
Скрипт для управления миграциями базы данных
"""

import subprocess
import sys
import os

def run_command(command, description):
    """Запускает команду и выводит результат"""
    print(f"🔄 {description}...")
    
    try:
        result = subprocess.run(
            [sys.executable, "-m"] + command,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Успешно")
            if result.stdout:
                print(result.stdout)
        else:
            print("❌ Ошибка:")
            print(result.stderr)
            return False
        
        return True
        
    except FileNotFoundError:
        print("❌ Alembic не найден. Установите: pip install alembic")
        return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

def main():
    """Основная функция"""
    print("=" * 50)
    print("🗄️  МЕНЕДЖЕР МИГРАЦИЙ БАЗЫ ДАННЫХ")
    print("=" * 50)
    
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python migrate.py init        - Инициализировать миграции")
        print("  python migrate.py create      - Создать новую миграцию")
        print("  python migrate.py upgrade     - Применить все миграции")
        print("  python migrate.py downgrade   - Откатить последнюю миграцию")
        print("  python migrate.py current     - Показать текущую миграцию")
        print("  python migrate.py history     - Показать историю миграций")
        print("  python migrate.py auto        - Автоматически создать и применить миграцию")
        return
    
    command = sys.argv[1]
    
    if command == "init":
        # Инициализация миграций
        print("📁 Инициализация миграций Alembic...")
        if not os.path.exists("alembic"):
            subprocess.run([sys.executable, "-m", "alembic", "init", "alembic"])
            print("✅ Папка alembic создана")
        else:
            print("ℹ️ Папка alembic уже существует")
        
    elif command == "create":
        if len(sys.argv) < 3:
            print("Укажите название миграции: python migrate.py create 'описание'")
            return
        message = sys.argv[2]
        run_command(["alembic", "revision", "--autogenerate", "-m", message], f"Создание миграции: {message}")
    
    elif command == "upgrade":
        if len(sys.argv) > 2:
            revision = sys.argv[2]
            run_command(["alembic", "upgrade", revision], f"Применение миграции до {revision}")
        else:
            run_command(["alembic", "upgrade", "head"], "Применение всех миграций")
    
    elif command == "downgrade":
        if len(sys.argv) > 2:
            revision = sys.argv[2]
            run_command(["alembic", "downgrade", revision], f"Откат до {revision}")
        else:
            run_command(["alembic", "downgrade", "-1"], "Откат последней миграции")
    
    elif command == "current":
        run_command(["alembic", "current"], "Текущая миграция")
    
    elif command == "history":
        run_command(["alembic", "history"], "История миграций")
    
    elif command == "auto":
        # Автоматически создаем и применяем миграцию
        print("🤖 АВТОМАТИЧЕСКАЯ МИГРАЦИЯ")
        print("=" * 30)
        
        # Проверяем текущее состояние
        print("📊 Проверка текущего состояния...")
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"Текущая миграция: {result.stdout.strip() if result.stdout else 'нет'}")
        else:
            print("ℹ️ Миграции не инициализированы")
        
        # Создаем автоматическую миграцию
        if run_command(["alembic", "revision", "--autogenerate", "-m", "Auto migration"], "Создание миграции"):
            # Применяем миграцию
            run_command(["alembic", "upgrade", "head"], "Применение миграции")
    
    else:
        print(f"❌ Неизвестная команда: {command}")

if __name__ == "__main__":
    main()