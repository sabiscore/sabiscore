"""Authentication token schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Token(BaseModel):
    """Access token returned after authentication."""

    access_token: str = Field(..., description="JWT access token string")
    token_type: str = Field(
        default="bearer", description="Token type, defaults to bearer"
    )
    expires_in: Optional[int] = Field(
        default=None,
        description="Optional expiry in seconds returned by the auth service",
        ge=1,
    )


class TokenPayload(BaseModel):
    """Token payload claims embedded in the JWT."""

    sub: str = Field(..., description="Subject identifier (user id or email)")
    exp: Optional[int] = Field(
        default=None, description="Unix timestamp for expiration"
    )
    iat: Optional[int] = Field(default=None, description="Issued-at timestamp")
    scope: Optional[str] = Field(
        default="api", description="Scope granted to this token"
    )
    issued_at: Optional[datetime] = Field(
        default=None,
        description="Server issued-at datetime retained for auditing",
    )


__all__ = ["Token", "TokenPayload"]
