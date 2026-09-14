"""Runtime SQLAlchemy compatibility layer for social-auth user fields.

The Alembic migration owns the physical schema. This module augments the
existing UserAccount mapper at import time so the auth surface can expose the
new nullable profile fields without rewriting the large legacy database model
module.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from ..core.database import Base


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        Index("ix_user_identities_user_id", "user_id"),
        Index("ix_user_identities_provider_subject", "provider", "provider_subject", unique=True),
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
