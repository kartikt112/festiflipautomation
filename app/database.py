"""Async SQLAlchemy database engine and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _normalize_db_url(url: str) -> str:
    """Normalize DB URL to use the correct async driver scheme."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url and "+aiopg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


_db_url = _normalize_db_url(settings.DATABASE_URL)

# Create async engine
_connect_args = {}
if "sqlite" in _db_url:
    # SQLite: increase busy timeout to handle concurrent writes gracefully
    _connect_args = {"timeout": 30}

engine = create_async_engine(
    _db_url,
    echo=(settings.APP_ENV == "development"),
    pool_pre_ping=True,
    connect_args=_connect_args,
)

# Session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables (used for development/testing)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
