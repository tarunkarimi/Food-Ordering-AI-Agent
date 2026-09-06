"""SQLAlchemy declarative base.

Models will be added in later roadmap phases. Keeping the base isolated here
lets Alembic discover those models without coupling database infrastructure to
any feature implementation.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass