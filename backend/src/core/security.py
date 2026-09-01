"""Security helpers for password hashing and JWT token handling."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

try:
	from jose import jwt, JWTError
except ImportError:
	import jwt  # type: ignore
	JWTError = getattr(jwt, "PyJWTError", Exception)  # type: ignore

try:
	from passlib.context import CryptContext
	_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception:
	_pwd_context = None

from .config import settings


def get_password_hash(password: str) -> str:
	"""Hash a password using bcrypt if available, otherwise PBKDF2."""
	try:
		import bcrypt
		salt = bcrypt.gensalt()
		return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
	except Exception:
		pass
	if _pwd_context is not None:
		try:
			return _pwd_context.hash(password)
		except Exception:
			pass
	import hashlib
	import os
	salt = os.urandom(16)
	key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
	return f"pbkdf2:${salt.hex()}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
	"""Verify password against bcrypt or PBKDF2 hash."""
	if hashed_password.startswith("pbkdf2:"):
		import hashlib
		import hmac
		parts = hashed_password.split("$")
		if len(parts) == 3:
			salt = bytes.fromhex(parts[1])
			expected = parts[2]
			computed = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100000).hex()
			return hmac.compare_digest(expected, computed)
		return False
	try:
		import bcrypt
		return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
	except Exception:
		pass
	if _pwd_context is not None:
		try:
			return _pwd_context.verify(plain_password, hashed_password)
		except Exception:
			pass
	return False


def create_access_token(
	subject: str,
	*,
	expires_delta: Optional[timedelta] = None,
	scope: str = "api",
	extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
	"""Create a signed JWT containing the provided subject and claims."""

	now = datetime.now(timezone.utc)
	expire_delta = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
	claims: Dict[str, Any] = {
		"sub": subject,
		"iat": now,
		"exp": now + expire_delta,
		"scope": scope,
	}
	if extra_claims:
		claims.update(extra_claims)
	return jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
	"""Decode a JWT and return its payload, raising JWTError on failure."""

	return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


__all__ = [
	"JWTError",
	"create_access_token",
	"decode_access_token",
	"get_password_hash",
	"verify_password",
]
