
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def _load_env_files() -> None:
    env = os.getenv("ENV", "development")
    candidates = [
        Path(f".env.{env}"),
        Path(".env"),
    ]
    for p in candidates:
        if p.exists():
            load_dotenv(p, override=False)


def _tables_for_mode(mode: str) -> List[str]:
    base = [
        "user_messages",
        "leads",
        "link_clicks",
        "subscribers",
        "bot_users",
    ]
    if mode == "full":
        return base + ["broadcasts"]
    if mode == "keep_broadcasts":
        return base
    raise ValueError(f"Unknown mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Очистка базы данных telegram_bot")
    parser.add_argument(
        "--mode",
        choices=["full", "keep_broadcasts"],
        default="full",
        help="full = удалить всё; keep_broadcasts = оставить broadcasts",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать SQL, но ничего не выполнять",
    )
    args = parser.parse_args()
    here = Path(__file__).resolve()
    project_root = here.parent.parent
    os.chdir(project_root)

    _load_env_files()

    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        print("❌ DATABASE_URL не найден (ни в env, ни в .env файлах).", file=sys.stderr)
        return 2

    tables = _tables_for_mode(args.mode)
    tables_sql = ", ".join(tables)
    sql = f"TRUNCATE TABLE {tables_sql} RESTART IDENTITY CASCADE;"

    print("⚠️ ВНИМАНИЕ: будет выполнена очистка БД!")
    print(f"ENV={os.getenv('ENV', 'development')}")
    print(f"DB: {db_url}")
    print(f"Mode: {args.mode}")
    print(f"SQL: {sql}")

    if args.dry_run:
        print("✅ DRY RUN — ничего не выполнено.")
        return 0

    engine = create_engine(db_url, pool_pre_ping=True)

    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
        print("✅ База очищена успешно.")
        return 0
    except Exception as e:
        print(f"❌ Ошибка очистки БД: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
