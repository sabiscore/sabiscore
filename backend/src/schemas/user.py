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
    """Shared public user attributes."""

    email: EmailStr
    username: Optional[str] = Field(default=None, min_length=3, max_length=32)
    full_name: Optional[str] = Field(default=None, max_length=200)
    avatar_url: Optional[str] = Field(default=None, max_length=1000)
    email_verified: bool = False
    is_active: bool = Field(default=True, description="Whether the user can authenticate")


class UserCreate(BaseModel):
    """Payload required to register a password account."""

    email: EmailStr
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=200)


class UserUpdate(BaseModel):
    """Partial profile update payload."""

    email: Optional[EmailStr] = None
    username: Optional[str] = Field(default=None, min_length=3, max_length=32)
    full_name: Optional[str] = Field(default=None, max_length=200)
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    avatar_url: Optional[str] = Field(default=None, max_length=1000)
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None


class UserInDBBase(BaseModel):
    """Base information persisted for a user record."""

    id: str
    email: EmailStr
    username: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email_verified: bool = False
    is_active: bool = True
    is_superuser: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class User(UserInDBBase):
    """Internal representation that includes authentication metadata."""

    hashed_password: Optional[str] = Field(default=None, repr=False)
    last_login_at: Optional[datetime] = None


class UserInDB(UserInDBBase):
    """Database representation with optional password for social accounts."""

    hashed_password: Optional[str] = Field(default=None, repr=False)


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
