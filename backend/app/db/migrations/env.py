import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import Base
from app.db.session import make_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str | None:
    # Tests (and scripts) can point alembic at another database via the "sqlalchemy.url" option.
    return config.get_main_option("sqlalchemy.url") or None


def run_migrations_offline() -> None:
    from app.config import get_settings

    context.configure(url=_url() or get_settings().database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine: AsyncEngine = make_engine(url=_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
