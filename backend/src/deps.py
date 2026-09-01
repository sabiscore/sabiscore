"""Reusable FastAPI dependencies for authentication and authorization."""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .core.config import settings
from .core.database import UserAccount
from .core.security import JWTError, decode_access_token
from .db.session import get_async_session
from .schemas.token import TokenPayload

oauth2_scheme = OAuth2PasswordBearer(
	tokenUrl=f"{settings.api_v1_str}/auth/token",
	scopes={"api": "Access the SabiScore API"},
)


async def _get_user_by_id(db: AsyncSession, user_id: str) -> UserAccount | None:
	result = await db.execute(select(UserAccount).where(UserAccount.id == user_id))
	return result.scalar_one_or_none()


async def get_current_user(
	token: str = Depends(oauth2_scheme),
	db: AsyncSession = Depends(get_async_session),
) -> UserAccount:
	"""Retrieve the authenticated user via bearer token."""

	credentials_error = HTTPException(
		status_code=status.HTTP_401_UNAUTHORIZED,
		detail="Could not validate credentials",
		headers={"WWW-Authenticate": "Bearer"},
	)

	try:
		payload = decode_access_token(token)
		token_data = TokenPayload.model_validate(payload)
	except (JWTError, ValidationError):
		raise credentials_error

	user = await _get_user_by_id(db, token_data.sub)
	if not user:
		raise credentials_error
	return user


async def get_current_active_user(
	current_user: UserAccount = Depends(get_current_user),
) -> UserAccount:
	"""Ensure the authenticated account is active."""

	if not current_user.is_active:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
	return current_user


__all__ = [
	"get_current_active_user",
	"get_current_user",
	"oauth2_scheme",
]
