"""Runtime SQLAlchemy compatibility layer for social-auth user fields.

The Alembic migration owns the physical schema. This module augments the
existing UserAccount mapper at import time so the auth surface can expose the
new nullable profile fields without rewriting the large legacy database model
module.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..core.database import Base, UserAccount


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        Index("ix_user_identities_user_id", "user_id"),
        # A UNIQUE CONSTRAINT, not a unique Index. PostgreSQL treats the two as
        # different objects (a constraint owns a backing index, but alembic
        # compares them separately), so declaring `Index(..., unique=True)`
        # here made `alembic check` propose dropping migration 0014's
        # constraint and adding an index in its place - on every commit.
        # The name must match 0014 exactly.
        UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_user_identities_provider_subject",
        ),
        {"extend_existing": True},
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String, nullable=False)
    provider_subject = Column(String, nullable=False)
    provider_email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    user = relationship("UserAccount", backref="identities")


def install_social_user_fields(user_account_model) -> None:
    """Attach migration-backed social profile columns to the existing mapper."""
    table = user_account_model.__table__
    mapper = user_account_model.__mapper__

    fields = (
        ("username", String(32), True, None),
        ("avatar_url", String(1000), True, None),
        ("email_verified", Boolean(), False, False),
    )

    for name, column_type, nullable, default in fields:
        if name in table.c:
            continue
        column = Column(name, column_type, nullable=nullable, default=default)
        table.append_column(column)
        mapper.add_property(name, column)

    if "username" in table.c:
        index_name = "ix_users_username"
        if not any(index.name == index_name for index in table.indexes):
            Index(index_name, table.c.username, unique=True)


# Install at import time, which is what this module's docstring has always
# claimed ("augments the existing UserAccount mapper at import time").
#
# It was not true: `install_social_user_fields` had exactly one caller,
# `api/endpoints/auth.py`, so the columns reached `Base.metadata` only when the
# FastAPI auth router was imported. Alembic's `env.py` imports the model
# modules and nothing else, so `alembic check` compared a database that HAD
# these columns (migration 0014 created them) against metadata that did NOT,
# and proposed dropping them - failing the schema-drift gate on every commit.
#
# Importing the whole auth endpoint from `env.py` would fix the symptom by
# pulling FastAPI and the entire endpoint chain into every migration run. Doing
# it here keeps the mapper definition and its installation in one module, which
# is where a reader looks for it.
#
# Idempotent by construction: every field is guarded by `if name in table.c`,
# so `auth.py`'s existing call remains harmless.
install_social_user_fields(UserAccount)
