"""Supabase (Postgres) bilan ishlash. Oddiy SQL, hech qanday sirli qatlam yo'q."""
from contextlib import asynccontextmanager

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from . import config

pool = AsyncConnectionPool(
    conninfo=config.DATABASE_URL,
    min_size=1,
    max_size=5,
    open=False,
    check=AsyncConnectionPool.check_connection,
    kwargs={"row_factory": dict_row, "prepare_threshold": None, "autocommit": True},
)


async def open_pool():
    await pool.open(wait=True, timeout=30)


async def close_pool():
    await pool.close()


async def q(sql, *params):
    """Ko'p qatorli so'rov -> list[dict]"""
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params or None)
        return await cur.fetchall() if cur.description else []


async def one(sql, *params):
    """Bitta qator yoki None"""
    rows = await q(sql, *params)
    return rows[0] if rows else None


async def ex(sql, *params):
    """Natija kerak bo'lmagan buyruq"""
    async with pool.connection() as conn:
        await conn.execute(sql, params or None)


@asynccontextmanager
async def tx():
    """Bir nechta buyruqni yagona tranzaksiyada bajarish.
    async with db.tx() as c:
        await c.execute(...)
    """
    async with pool.connection() as conn:
        async with conn.transaction():
            yield conn


def js(obj):
    return Jsonb(obj)
