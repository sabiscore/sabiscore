"""Authentication, user profile, anonymous session, favorites, and preference endpoints."""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.database import UserAccount
from ...core.security import create_access_token, get_password_hash, verify_password
from ...db.session import get_async_session
from ...deps import get_current_active_user
from ...schemas.auth import LoginRequest, LoginResponse
from ...schemas.token import Token
from ...schemas.user import UserCreate, UserResponse
from ...services.auth_service import UserStateService, get_anon_id_from_request, get_optional_user_from_request

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])

AUTH_RATE_LIMIT_REQUESTS = 20
AUTH_RATE_LIMIT_WINDOW = 60
_rate_limit_store: dict[str, list[datetime]] = defaultdict(list)
_rate_lock = asyncio.Lock()


# ── Pydantic Schemas for Favorites, Saved Matches, & Preferences ──────────────

class FavoriteCreate(BaseModel):
    entity_type: str = Field(..., description="'team' or 'competition'")
    entity_id: str = Field(..., description="Team slug or competition code (e.g., 'arsenal', 'EPL')")


class FavoriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: Optional[str] = None
    anonymous_session_id: Optional[str] = None
    entity_type: str
    entity_id: str
    created_at: datetime


class SavedMatchCreate(BaseModel):
    match_id: str = Field(..., description="Target match ID")
    target_outcome: Optional[str] = Field(None, description="'HOME_WIN', 'DRAW', or 'AWAY_WIN'")
    notes: Optional[str] = Field(None, max_length=500)


class SavedMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: Optional[str] = None
    anonymous_session_id: Optional[str] = None
    match_id: str
    target_outcome: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class PreferenceUpdate(BaseModel):
    odds_format: Optional[str] = Field(None, description="'DECIMAL', 'FRACTIONAL', or 'AMERICAN'")
    timezone: Optional[str] = Field(None, description="IANA timezone name, e.g. 'Africa/Lagos'")
    default_league: Optional[str] = Field(None, description="Default league filter, e.g. 'EPL'")


class PreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: Optional[str] = None
    anonymous_session_id: Optional[str] = None
    odds_format: str
    timezone: str
    default_league: Optional[str] = None
    updated_at: datetime


class MergeAnonymousRequest(BaseModel):
    anonymous_session_id: Optional[str] = Field(None, description="Anonymous device ID to merge from")


class MergeAnonymousResponse(BaseModel):
    status: str
    user_id: str
    anonymous_session_id: str
    merged_favorites: int
    merged_saved_matches: int


# ── Auth Helpers ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OAuthPasswordForm:
    username: str
    password: str
    scopes: list[str]


async def oauth_password_form(
    username: str = Form(...),
    password: str = Form(...),
    scope: str = Form(default=""),
) -> OAuthPasswordForm:
    """Parse OAuth2 password form data without FastAPI's fragile helper class."""
    scopes = [item for item in scope.split() if item]
    return OAuthPasswordForm(username=username, password=password, scopes=scopes)


async def _check_rate_limit(client_ip: str) -> None:
    async with _rate_lock:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=AUTH_RATE_LIMIT_WINDOW)
        recent = [ts for ts in _rate_limit_store[client_ip] if ts > window_start]
        _rate_limit_store[client_ip] = recent
        if len(recent) >= AUTH_RATE_LIMIT_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many authentication attempts. Please wait a moment.",
            )
        recent.append(now)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _client_ip(request: Request) -> str:
    return (request.client.host if request.client else "unknown") or "unknown"


async def _get_user_by_email(db: AsyncSession, email: str) -> Optional[UserAccount]:
    result = await db.execute(select(UserAccount).where(UserAccount.email == email))
    return result.scalar_one_or_none()


async def _authenticate_user(db: AsyncSession, email: str, password: str) -> Optional[UserAccount]:
    user = await _get_user_by_email(db, _normalize_email(email))
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def _token_expiry_delta(remember_me: bool) -> timedelta:
    base_minutes = settings.access_token_expire_minutes
    if remember_me:
        return timedelta(minutes=min(base_minutes * 3, 60 * 24 * 14))  # cap at 14 days
    return timedelta(minutes=base_minutes)


def _serialize_user(user: UserAccount) -> UserResponse:
    return UserResponse.model_validate(user)


async def _touch_last_login(db: AsyncSession, user: UserAccount) -> None:
    user.last_login_at = datetime.now(timezone.utc)
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)


# ── Auth Endpoints ────────────────────────────────────────────────────────────

@auth_router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_session),
):
    """Register a new user account with hashed password storage."""
    await _check_rate_limit(_client_ip(request))
    email = _normalize_email(str(payload.email))

    existing = await _get_user_by_email(db, email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = UserAccount(
        email=email,
        full_name=payload.full_name,
        hashed_password=get_password_hash(payload.password),
        is_active=payload.is_active,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Optional auto-merge if anonymous session exists
    anon_id = get_anon_id_from_request(request)
    if anon_id:
        try:
            await UserStateService.merge_anonymous_state(db, user_id=str(user.id), anonymous_session_id=anon_id)
        except Exception:
            pass

    return _serialize_user(user)


@auth_router.post("/login", response_model=LoginResponse)
async def login_user(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_session),
):
    """Login with JSON credentials and receive a JWT plus profile payload."""
    await _check_rate_limit(_client_ip(request))
    user = await _authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    expires_delta = _token_expiry_delta(payload.remember_me)
    token = create_access_token(str(user.id), expires_delta=expires_delta, scope=payload.scope)
    await _touch_last_login(db, user)

    # Set httpOnly session cookie for seamless secure browser authentication
    response.set_cookie(
        key="sabi_session",
        value=token,
        max_age=int(expires_delta.total_seconds()),
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )

    # Optional auto-merge if anonymous session cookie exists
    anon_id = get_anon_id_from_request(request)
    if anon_id:
        try:
            await UserStateService.merge_anonymous_state(db, user_id=str(user.id), anonymous_session_id=anon_id)
        except Exception:
            pass

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=int(expires_delta.total_seconds()),
        user=_serialize_user(user),
    )


@auth_router.post("/cookie-login", response_model=LoginResponse)
async def cookie_login_user(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_session),
):
    """Login and exclusively set httpOnly cookie for zero-localStorage browser architectures."""
    return await login_user(payload=payload, request=request, response=response, db=db)


@auth_router.post("/logout")
async def logout_user(response: Response):
    """Clear httpOnly authentication session cookies."""
    response.delete_cookie(key="sabi_session", path="/")
    return {"status": "LOGGED_OUT"}


@auth_router.post("/token", response_model=Token)
async def login_via_oauth_form(
    request: Request,
    form_data: OAuthPasswordForm = Depends(oauth_password_form),
    db: AsyncSession = Depends(get_async_session),
):
    """OAuth2-compatible token endpoint used by the interactive docs."""
    await _check_rate_limit(_client_ip(request))
    user = await _authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    scope = " ".join(form_data.scopes) if form_data.scopes else "api"
    expires_delta = _token_expiry_delta(False)
    token = create_access_token(str(user.id), expires_delta=expires_delta, scope=scope)
    await _touch_last_login(db, user)

    return Token(access_token=token, token_type="bearer", expires_in=int(expires_delta.total_seconds()))


@auth_router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserAccount = Depends(get_current_active_user)) -> UserResponse:
    """Return the authenticated user's profile."""
    return _serialize_user(current_user)


# ── User & Anonymous State Endpoints (/users/...) ────────────────────────────

@users_router.post("/merge-anonymous", response_model=MergeAnonymousResponse)
async def merge_anonymous(
    payload: MergeAnonymousRequest,
    request: Request,
    current_user: UserAccount = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Merge an anonymous visitor's saved matches, favorites, and preferences into the authenticated user."""
    anon_id = payload.anonymous_session_id or get_anon_id_from_request(request)
    if not anon_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No anonymous session identifier provided or found in headers/cookies",
        )

    result = await UserStateService.merge_anonymous_state(
        db, user_id=str(current_user.id), anonymous_session_id=anon_id
    )
    return MergeAnonymousResponse(
        status=result["status"],
        user_id=result["user_id"],
        anonymous_session_id=result["anonymous_session_id"],
        merged_favorites=result["merged_favorites"],
        merged_saved_matches=result["merged_saved_matches"],
    )


# ── Favorites Endpoints ───────────────────────────────────────────────────────

@users_router.get("/favorites", response_model=List[FavoriteResponse])
async def list_favorites(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """List favorite teams and competitions for the current user or anonymous session."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        return []

    favs = await UserStateService.get_favorites(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    return [FavoriteResponse.model_validate(f) for f in favs]


@users_router.post("/favorites", response_model=FavoriteResponse, status_code=status.HTTP_201_CREATED)
async def add_favorite(
    payload: FavoriteCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Add a favorite team or competition for current user or anonymous session."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        anon_id = str(uuid.uuid4())

    fav = await UserStateService.add_favorite(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
    )
    return FavoriteResponse.model_validate(fav)


@users_router.delete("/favorites/{favorite_id}")
async def delete_favorite_by_id(
    favorite_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Remove a favorite item by ID."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication or anonymous session required")

    success = await UserStateService.remove_favorite(
        db,
        favorite_id=favorite_id,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Favorite item not found")
    return {"status": "DELETED", "id": favorite_id}


@users_router.delete("/favorites")
async def delete_favorite_by_entity(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Remove a favorite item by entity type and entity ID."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication or anonymous session required")

    success = await UserStateService.remove_favorite(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    return {"status": "DELETED" if success else "NOT_FOUND"}


# ── Saved Matches Endpoints ───────────────────────────────────────────────────

@users_router.get("/saved-matches", response_model=List[SavedMatchResponse])
async def list_saved_matches(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """List saved matches for the current user or anonymous visitor."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        return []

    matches = await UserStateService.get_saved_matches(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    return [SavedMatchResponse.model_validate(m) for m in matches]


@users_router.post("/saved-matches", response_model=SavedMatchResponse, status_code=status.HTTP_201_CREATED)
async def save_match(
    payload: SavedMatchCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Save a match to personal watchlist."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        anon_id = str(uuid.uuid4())

    saved = await UserStateService.save_match(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
        match_id=payload.match_id,
        target_outcome=payload.target_outcome,
        notes=payload.notes,
    )
    return SavedMatchResponse.model_validate(saved)


@users_router.delete("/saved-matches/{match_id}")
async def remove_saved_match(
    match_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Remove a match from personal watchlist."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication or anonymous session required")

    success = await UserStateService.remove_saved_match(
        db,
        match_id=match_id,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved match not found")
    return {"status": "DELETED", "match_id": match_id}


# ── User Preferences Endpoints ────────────────────────────────────────────────

@users_router.get("/preferences", response_model=PreferenceResponse)
async def get_user_preferences(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Retrieve personal preferences (odds format, timezone, default league)."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    pref = await UserStateService.get_preferences(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    return PreferenceResponse.model_validate(pref)


@users_router.put("/preferences", response_model=PreferenceResponse)
async def update_user_preferences(
    payload: PreferenceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Update personal preferences."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        anon_id = str(uuid.uuid4())

    pref = await UserStateService.update_preferences(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
        odds_format=payload.odds_format,
        timezone_pref=payload.timezone,
        default_league=payload.default_league,
    )
    return PreferenceResponse.model_validate(pref)


# Combined router for inclusion in endpoints/__init__.py
router = APIRouter()
router.include_router(auth_router)
router.include_router(users_router)

__all__ = ["router", "auth_router", "users_router"]
