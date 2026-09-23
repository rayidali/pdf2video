"""Job persistence: one JSON document per job.

SQLite locally (stdlib, zero setup). Postgres on Vercel via DATABASE_URL, which the
Marketplace integration injects. Both expose the same async interface, and both open a
connection per call, which is the right shape for serverless.
"""
import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional, Protocol

from app.models.schemas import Job, utcnow

logger = logging.getLogger(__name__)


class JobStore(Protocol):
    async def create(self, job: Job) -> None: ...
    async def save(self, job: Job) -> None: ...
    async def get(self, job_id: str) -> Optional[Job]: ...
    async def list(self, limit: int = 50) -> list[dict]: ...


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

class SqliteJobStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._ready = False

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        if not self._ready:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                " id TEXT PRIMARY KEY, data TEXT NOT NULL,"
                " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.commit()
            self._ready = True
        return conn

    def _upsert(self, job: Job) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO jobs (id, data, created_at, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                (job.id, job.model_dump_json(), job.created_at, job.updated_at),
            )

    def _get(self, job_id: str) -> Optional[Job]:
        with self._conn() as conn:
            row = conn.execute("SELECT data FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def _list(self, limit: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT data FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Job.model_validate_json(r[0]).summary() for r in rows]

    async def create(self, job: Job) -> None:
        await asyncio.to_thread(self._upsert, job)

    async def save(self, job: Job) -> None:
        job.updated_at = utcnow()
        await asyncio.to_thread(self._upsert, job)

    async def get(self, job_id: str) -> Optional[Job]:
        return await asyncio.to_thread(self._get, job_id)

    async def list(self, limit: int = 50) -> list[dict]:
        return await asyncio.to_thread(self._list, limit)


# ---------------------------------------------------------------------------
# Postgres (Neon or any Marketplace Postgres)
# ---------------------------------------------------------------------------

class PostgresJobStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._ready = False

    async def _connect(self):
        import psycopg  # imported lazily so local dev and tests never need it

        conn = await psycopg.AsyncConnection.connect(self.dsn, autocommit=True)
        if not self._ready:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                " id TEXT PRIMARY KEY, data JSONB NOT NULL,"
                " created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)"
            )
            self._ready = True
        return conn

    async def _upsert(self, job: Job) -> None:
        from psycopg.types.json import Jsonb

        async with await self._connect() as conn:
            await conn.execute(
                "INSERT INTO jobs (id, data, created_at, updated_at) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at",
                (job.id, Jsonb(json.loads(job.model_dump_json())), job.created_at, job.updated_at),
            )

    async def create(self, job: Job) -> None:
        await self._upsert(job)

    async def save(self, job: Job) -> None:
        job.updated_at = utcnow()
        await self._upsert(job)

    async def get(self, job_id: str) -> Optional[Job]:
        async with await self._connect() as conn:
            cur = await conn.execute("SELECT data FROM jobs WHERE id = %s", (job_id,))
            row = await cur.fetchone()
        return Job.model_validate(row[0]) if row else None

    async def list(self, limit: int = 50) -> list[dict]:
        async with await self._connect() as conn:
            cur = await conn.execute(
                "SELECT data FROM jobs ORDER BY created_at DESC LIMIT %s", (limit,)
            )
            rows = await cur.fetchall()
        return [Job.model_validate(r[0]).summary() for r in rows]


def build_store(database_url: str, sqlite_path: Path | str) -> JobStore:
    if database_url:
        logger.info("Job store: Postgres")
        return PostgresJobStore(database_url)
    logger.info(f"Job store: SQLite at {sqlite_path}")
    return SqliteJobStore(sqlite_path)
