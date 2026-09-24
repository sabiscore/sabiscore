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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.database import UserAccount
from ...services.social_auth_models import UserIdentity, install_social_user_fields
from ...core.security import create_access_token, get_password_hash, verify_password
from ...db.session import get_async_session
from ...schemas.auth import GoogleOAuthRequest, LoginRequest, LoginResponse
from ...schemas.token import Token
from ...schemas.user import UserCreate, UserResponse
from ...services.auth_service import (
    UserStateService,
    get_anon_id_from_request,
    get_optional_user_from_request,
    get_required_user_from_request,
)
from ...services.google_oauth import GoogleOAuthError, verify_google_id_token

install_social_user_fields(UserAccount)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])

AUTH_RATE_LIMIT_REQUESTS = 20
AUTH_RATE_LIMIT_WINDOW = 60
_rate_limit_store: dict[str, list[datetime]] = defaultdict(list)
_rate_lock = asyncio.Lock()


class FavoriteCreate(BaseModel):
    entity_type: str = Field(..., description="'team' or 'competition'")
    entity_id: str = Field(
        ..., description="Team slug or competition code (e.g., 'arsenal', 'EPL')"
    )


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
    target_outcome: Optional[str] = Field(
        None, description="'HOME_WIN', 'DRAW', or 'AWAY_WIN'"
    )
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
    odds_format: Optional[str] = Field(
        None, description="'DECIMAL', 'FRACTIONAL', or 'AMERICAN'"
    )
    timezone: Optional[str] = Field(
        None, description="IANA timezone name, e.g. 'Africa/Lagos'"
    )
    default_league: Optional[str] = Field(
        None, description="Default league filter, e.g. 'EPL'"
    )


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
    anonymous_session_id: Optional[str] = Field(
        None, description="Anonymous device ID to merge from"
    )


class MergeAnonymousResponse(BaseModel):
    status: str
    user_id: str
    anonymous_session_id: str
    merged_favorites: int
    merged_saved_matches: int


@dataclass(frozen=True)
class OAuthPasswordForm:
    username: str
    password: str
    scopes: list[str]


async def oauth_password_form(
    username: str = Form(...), password: str = Form(...), scope: str = Form(default="")
) -> OAuthPasswordForm:
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


def _normalize_username(username: str) -> str:
    return username.strip().lower()


async def _username_exists(db: AsyncSession, username: str) -> bool:
    result = await db.execute(
        select(UserAccount.id).where(UserAccount.username == username)
    )
    return result.scalar_one_or_none() is not None


async def _unique_username(db: AsyncSession, preferred: str) -> str:
    base = _normalize_username(preferred)
    base = "".join(ch for ch in base if ch.isalnum() or ch in "._-")
    base = base.strip("._-")[:24] or "analyst"
    if not await _username_exists(db, base):
        return base
    for suffix in range(2, 1000):
        candidate = f"{base[: max(1, 32 - len(str(suffix)) - 1)]}-{suffix}"
        if not await _username_exists(db, candidate):
            return candidate
    return f"analyst-{uuid.uuid4().hex[:10]}"


def _client_ip(request: Request) -> str:
    return (request.client.host if request.client else "unknown") or "unknown"


async def _get_user_by_email(db: AsyncSession, email: str) -> Optional[UserAccount]:
    result = await db.execute(select(UserAccount).where(UserAccount.email == email))
    return result.scalar_one_or_none()


async def _authenticate_user(
    db: AsyncSession, email: str, password: str
) -> Optional[UserAccount]:
    user = await _get_user_by_email(db, _normalize_email(email))
    if not user or not user.hashed_password:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def _token_expiry_delta(remember_me: bool) -> timedelta:
    base_minutes = settings.access_token_expire_minutes
    if remember_me:
        return timedelta(minutes=min(base_minutes * 3, 60 * 24 * 14))
    return timedelta(minutes=base_minutes)


def _serialize_user(user: UserAccount) -> UserResponse:
    return UserResponse.model_validate(user)


async def _touch_last_login(db: AsyncSession, user: UserAccount) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user.last_login_at = now
    user.updated_at = now
    await db.commit()
    await db.refresh(user)


@auth_router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register_user(
    payload: UserCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_session),
):
    await _check_rate_limit(_client_ip(request))
    email = _normalize_email(str(payload.email))
    existing = await _get_user_by_email(db, email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )
    username = _normalize_username(payload.username)
    if await _username_exists(db, username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already registered"
        )
    user = UserAccount(
        email=email,
        username=username,
        full_name=payload.full_name or username,
        hashed_password=get_password_hash(payload.password),
        email_verified=False,
        is_active=True,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        detail = str(exc.orig).lower() if exc.orig else ""
        if "username" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already registered",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered",
        ) from exc
    await db.refresh(user)
    anon_id = get_anon_id_from_request(request)
    if anon_id:
        try:
            await UserStateService.merge_anonymous_state(
                db, user_id=str(user.id), anonymous_session_id=anon_id
            )
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
    await _check_rate_limit(_client_ip(request))
    user = await _authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )
    expires_delta = _token_expiry_delta(payload.remember_me)
    token = create_access_token(
        str(user.id), expires_delta=expires_delta, scope=payload.scope
    )
    await _touch_last_login(db, user)
    response.set_cookie(
        key="sabi_session",
        value=token,
        max_age=int(expires_delta.total_seconds()),
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )
    anon_id = get_anon_id_from_request(request)
    if anon_id:
        try:
            await UserStateService.merge_anonymous_state(
                db, user_id=str(user.id), anonymous_session_id=anon_id
            )
        except Exception:
            pass
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=int(expires_delta.total_seconds()),
        user=_serialize_user(user),
    )


@auth_router.post("/oauth/google", response_model=LoginResponse)
async def login_with_google(
    payload: GoogleOAuthRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_session),
):
    await _check_rate_limit(_client_ip(request))
    try:
        claims = await verify_google_id_token(payload.id_token, payload.nonce)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    subject = claims["sub"]
    email = _normalize_email(claims["email"])
    identity_result = await db.execute(
        select(UserIdentity).where(
            UserIdentity.provider == "google", UserIdentity.provider_subject == subject
        )
    )
    identity = identity_result.scalar_one_or_none()
    user: Optional[UserAccount] = None
    if identity:
        user_result = await db.execute(
            select(UserAccount).where(UserAccount.id == identity.user_id)
        )
        user = user_result.scalar_one_or_none()
    if user is None:
        user = await _get_user_by_email(db, email)
        if user is None:
            username = await _unique_username(db, email.split("@", 1)[0])
            user = UserAccount(
                email=email,
                username=username,
                full_name=claims.get("name") or username,
                avatar_url=claims.get("picture"),
                email_verified=True,
                hashed_password=None,
                is_active=True,
            )
            db.add(user)
            await db.flush()
        elif not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
            )
        if identity is None:
            identity = UserIdentity(
                user_id=str(user.id),
                provider="google",
                provider_subject=subject,
                provider_email=email,
            )
            db.add(identity)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user.email_verified = True
    if claims.get("name") and not user.full_name:
        user.full_name = claims["name"]
    if claims.get("picture") and not user.avatar_url:
        user.avatar_url = claims["picture"]
    user.last_login_at = now
    user.updated_at = now
    if identity:
        identity.provider_email = email
        identity.last_login_at = now
    await db.commit()
    await db.refresh(user)
    expires_delta = _token_expiry_delta(payload.remember_me)
    token = create_access_token(str(user.id), expires_delta=expires_delta, scope="api")
    response.set_cookie(
        key="sabi_session",
        value=token,
        max_age=int(expires_delta.total_seconds()),
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )
    anon_id = get_anon_id_from_request(request)
    if anon_id:
        try:
            await UserStateService.merge_anonymous_state(
                db, user_id=str(user.id), anonymous_session_id=anon_id
            )
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
    return await login_user(payload=payload, request=request, response=response, db=db)


@auth_router.post("/logout")
async def logout_user(response: Response):
    response.delete_cookie(key="sabi_session", path="/")
    return {"status": "LOGGED_OUT"}


@auth_router.post("/token", response_model=Token)
async def login_via_oauth_form(
    request: Request,
    form_data: OAuthPasswordForm = Depends(oauth_password_form),
    db: AsyncSession = Depends(get_async_session),
):
    await _check_rate_limit(_client_ip(request))
    user = await _authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )
    scope = " ".join(form_data.scopes) if form_data.scopes else "api"
    expires_delta = _token_expiry_delta(False)
    token = create_access_token(str(user.id), expires_delta=expires_delta, scope=scope)
    await _touch_last_login(db, user)
    return Token(
        access_token=token,
        token_type="bearer",
        expires_in=int(expires_delta.total_seconds()),
    )


@auth_router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: UserAccount = Depends(get_required_user_from_request),
) -> UserResponse:
    return _serialize_user(current_user)


@users_router.post("/merge-anonymous", response_model=MergeAnonymousResponse)
async def merge_anonymous(
    payload: MergeAnonymousRequest,
    request: Request,
    current_user: UserAccount = Depends(get_required_user_from_request),
    db: AsyncSession = Depends(get_async_session),
):
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


@users_router.get("/favorites", response_model=List[FavoriteResponse])
async def list_favorites(
    request: Request, db: AsyncSession = Depends(get_async_session)
):
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


@users_router.post(
    "/favorites", response_model=FavoriteResponse, status_code=status.HTTP_201_CREATED
)
async def add_favorite(
    payload: FavoriteCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
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
    favorite_id: str, request: Request, db: AsyncSession = Depends(get_async_session)
):
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)
    if not user and not anon_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication or anonymous session required",
        )
    success = await UserStateService.remove_favorite(
        db,
        favorite_id=favorite_id,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Favorite item not found"
        )
    return {"status": "DELETED", "id": favorite_id}


@users_router.delete("/favorites")
async def delete_favorite_by_entity(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)
    if not user and not anon_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication or anonymous session required",
        )
    success = await UserStateService.remove_favorite(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    return {"status": "DELETED" if success else "NOT_FOUND"}


@users_router.get("/saved-matches", response_model=List[SavedMatchResponse])
async def list_saved_matches(
    request: Request, db: AsyncSession = Depends(get_async_session)
):
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


@users_router.post(
    "/saved-matches",
    response_model=SavedMatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_match(
    payload: SavedMatchCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
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
    match_id: str, request: Request, db: AsyncSession = Depends(get_async_session)
):
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)
    if not user and not anon_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication or anonymous session required",
        )
    success = await UserStateService.remove_saved_match(
        db,
        match_id=match_id,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Saved match not found"
        )
    return {"status": "DELETED", "match_id": match_id}


@users_router.get("/preferences", response_model=PreferenceResponse)
async def get_user_preferences(
    request: Request, db: AsyncSession = Depends(get_async_session)
):
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


router = APIRouter()
router.include_router(auth_router)
router.include_router(users_router)

__all__ = ["router", "auth_router", "users_router"]
