"""Restore a Protogen backup (protogen-*.json.gz) into an EMPTY database.

    1. Start the site once against the new database so all tables are created.
    2. DATABASE_URL=postgresql://... python tools/restore_backup.py protogen-BKP-xxxx.json.gz

Tables that already contain rows are skipped (use --force to append anyway).
"""
import gzip
import json
import os
import sys
from datetime import datetime

from sqlalchemy import DateTime, MetaData, create_engine, func, select, text


def engine_from_env():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL не задан — восстанавливаю в локальный database.db")
        return create_engine("sqlite:///database.db")
    url = url.replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    force = "--force" in sys.argv
    with gzip.open(sys.argv[1], "rb") as fh:
        payload = json.loads(fh.read().decode("utf-8"))
    if payload.get("schema") != "protogen-logical-v1":
        sys.exit("Это не бэкап Protogen (schema != protogen-logical-v1).")

    engine = engine_from_env()
    meta = MetaData()
    meta.reflect(bind=engine)
    restored = 0
    with engine.begin() as conn:
        for name, rows in payload["tables"].items():
            table = meta.tables.get(name)
            if table is None or not rows:
                continue
            existing = conn.execute(select(func.count()).select_from(table)).scalar()
            if existing and not force:
                print(f"  пропуск {name}: в таблице уже {existing} строк")
                continue
            columns = {c.name: c for c in table.columns}
            clean = []
            for row in rows:
                item = {}
                for k, v in row.items():
                    col = columns.get(k)
                    if col is None:
                        continue
                    if isinstance(col.type, DateTime) and isinstance(v, str):
                        try:
                            v = datetime.fromisoformat(v.replace("Z", ""))
                        except ValueError:
                            v = None
                    item[k] = v
                clean.append(item)
            conn.execute(table.insert(), clean)
            restored += len(clean)
            print(f"  {name}: {len(clean)}")
            if engine.dialect.name == "postgresql" and "id" in columns:
                conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('\"{name}\"', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{name}\"), 1))"))
    print(f"Готово: восстановлено строк {restored} из бэкапа {payload.get('backup_id')}")


if __name__ == "__main__":
    main()
