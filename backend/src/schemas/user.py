"""User-facing Pydantic schemas for FastAPI routes."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

try:
	import email_validator  # noqa: F401
	from pydantic import EmailStr
except ImportError:
	EmailStr = str  # type: ignore


class UserBase(BaseModel):
	"""Shared user attributes exposed across multiple schema variants."""

	email: EmailStr
	full_name: Optional[str] = Field(default=None, max_length=200)
	is_active: bool = Field(default=True, description="Whether the user can authenticate")


class UserCreate(UserBase):
	"""Payload required to register a new user."""

	password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
	"""Partial update payload for existing users."""

	email: Optional[EmailStr] = None
	full_name: Optional[str] = Field(default=None, max_length=200)
	password: Optional[str] = Field(default=None, min_length=8, max_length=128)
	is_active: Optional[bool] = None
	is_superuser: Optional[bool] = None


class UserInDBBase(UserBase):
	"""Base information persisted for a user record."""

	id: str
	is_superuser: bool = False
	created_at: Optional[datetime] = None
	updated_at: Optional[datetime] = None

	model_config = ConfigDict(from_attributes=True)


class User(UserInDBBase):
	"""Internal representation that includes authentication metadata."""

	hashed_password: Optional[str] = Field(default=None, repr=False)
	last_login_at: Optional[datetime] = None


class UserInDB(UserInDBBase):
	"""Database model with required hashed password."""

	hashed_password: str = Field(repr=False)


class UserResponse(UserInDBBase):
	"""Response model returned by public user APIs."""

	last_login_at: Optional[datetime] = None


__all__ = [
	"User",
	"UserCreate",
	"UserInDB",
	"UserUpdate",
	"UserResponse",
]
