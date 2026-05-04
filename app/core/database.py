"""Database session and base setup."""
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


# SQLite requires special connect args for FastAPI's threadpool
connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables() -> None:
    """Create all tables. Used for local dev only - production uses Alembic."""
    # Import all models so SQLAlchemy registers them
    from app.modules.mdm import models as mdm_models  # noqa: F401
    from app.modules.sd import models as sd_models    # noqa: F401
    from app.modules.pp import models as pp_models    # noqa: F401
    from app.modules.pp import execution_models       # noqa: F401
    from app.modules.mm import models as mm_models    # noqa: F401
    from app.modules.fi import models as fi_models    # noqa: F401
    from app.modules.hr import models as hr_models    # noqa: F401
    from app.modules.gts import models as gts_models  # noqa: F401
    from app.core import auth_models                  # noqa: F401
    from app.core import numbering as _numbering      # noqa: F401

    Base.metadata.create_all(bind=engine)
