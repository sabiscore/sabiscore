"""Authentication request/response schemas."""

from pydantic import BaseModel, Field

try:
    import email_validator  # noqa: F401
    from pydantic import EmailStr
except ImportError:
    EmailStr = str  # type: ignore

from .token import Token
from .user import UserResponse


class LoginRequest(BaseModel):
    """Credentials payload submitted by clients when requesting a token."""

    email: EmailStr = Field(..., description="User email used as login identifier")
    password: str = Field(..., min_length=8, max_length=128)
    scope: str = Field(default="api", description="Optional OAuth-style scope identifier")
    remember_me: bool = Field(default=False, description="Extend token lifetime if true")


class LoginResponse(Token):
    """Token response bundled with the hydrated user profile."""

    user: UserResponse


__all__ = ["LoginRequest", "LoginResponse"]
