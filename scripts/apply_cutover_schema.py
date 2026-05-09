import asyncio
from pathlib import Path

import asyncpg


DSN = "postgresql://supplychain:supplychain_secret@localhost:5432/supplychain"


async def main() -> None:
    migration_sql = Path("infra/postgres/04-cutover-migration.sql").read_text(encoding="utf-8")
    init_sql = Path("infra/postgres/init.sql").read_text(encoding="utf-8")

    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(migration_sql)
        await conn.execute(init_sql)
        print("schema_applied")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
