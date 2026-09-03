"""User state, favorites, saved matches, preferences, and anonymous session service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import Request
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import UserAccount
from ..core.security import decode_access_token
from ..db.models import (
    UserFavorite,
    UserNotificationLog,
    UserNotificationSubscription,
    UserPreference,
    UserSavedMatch,
)


def _naive_utc_now() -> datetime:
    """UTC "now" with tzinfo stripped.

    UserFavorite/UserSavedMatch/UserPreference all use naive `DateTime`
    columns; asyncpg raises "can't subtract offset-naive and offset-aware
    datetimes" at bind time if handed a tz-aware value (same bug class
    documented elsewhere in this codebase for naive DateTime columns) — every
    stored timestamp in this file must be stripped of tzinfo before
    assignment.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_anon_id_from_request(request: Request) -> Optional[str]:
    """Extract anonymous session ID from header or cookie."""
    header_val = request.headers.get("X-Anonymous-Session") or request.headers.get("X-Anon-Id")
    if header_val:
        return header_val.strip()
    cookie_val = request.cookies.get("sabi_anon_id")
    if cookie_val:
        return cookie_val.strip()
    return None


async def get_optional_user_from_request(
    request: Request, db: AsyncSession
) -> Optional[UserAccount]:
    """Extract authenticated user from Authorization header or sabi_session cookie if present."""
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    elif "sabi_session" in request.cookies:
        token = request.cookies.get("sabi_session")

    if not token:
        return None

    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        result = await db.execute(select(UserAccount).where(UserAccount.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
    except Exception:
        return None
    return None


class UserStateService:
    """Service managing user preferences, favorites, saved matches, and anonymous state merging."""

    @staticmethod
    async def add_favorite(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        entity_type: str,
        entity_id: str,
    ) -> UserFavorite:
        if not user_id and not anonymous_session_id:
            raise ValueError("Either user_id or anonymous_session_id must be provided")

        entity_type_clean = entity_type.strip().lower()
        entity_id_clean = entity_id.strip()

        # Check for existing duplicate
        if user_id:
            stmt = select(UserFavorite).where(
                UserFavorite.user_id == user_id,
                UserFavorite.entity_type == entity_type_clean,
                UserFavorite.entity_id == entity_id_clean,
            )
        else:
            stmt = select(UserFavorite).where(
                UserFavorite.anonymous_session_id == anonymous_session_id,
                UserFavorite.entity_type == entity_type_clean,
                UserFavorite.entity_id == entity_id_clean,
            )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        fav = UserFavorite(
            id=str(uuid.uuid4()),
            user_id=user_id,
            anonymous_session_id=anonymous_session_id if not user_id else None,
            entity_type=entity_type_clean,
            entity_id=entity_id_clean,
            created_at=_naive_utc_now(),
        )
        db.add(fav)
        await db.commit()
        await db.refresh(fav)
        return fav

    @staticmethod
    async def get_favorites(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
    ) -> List[UserFavorite]:
        if not user_id and not anonymous_session_id:
            return []

        if user_id:
            stmt = select(UserFavorite).where(UserFavorite.user_id == user_id)
        else:
            stmt = select(UserFavorite).where(
                UserFavorite.anonymous_session_id == anonymous_session_id
            )
        stmt = stmt.order_by(UserFavorite.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def remove_favorite(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        favorite_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> bool:
        if not user_id and not anonymous_session_id:
            return False

        if favorite_id:
            if user_id:
                stmt = delete(UserFavorite).where(
                    UserFavorite.id == favorite_id,
                    UserFavorite.user_id == user_id,
                )
            else:
                stmt = delete(UserFavorite).where(
                    UserFavorite.id == favorite_id,
                    UserFavorite.anonymous_session_id == anonymous_session_id,
                )
        elif entity_type and entity_id:
            if user_id:
                stmt = delete(UserFavorite).where(
                    UserFavorite.user_id == user_id,
                    UserFavorite.entity_type == entity_type.strip().lower(),
                    UserFavorite.entity_id == entity_id.strip(),
                )
            else:
                stmt = delete(UserFavorite).where(
                    UserFavorite.anonymous_session_id == anonymous_session_id,
                    UserFavorite.entity_type == entity_type.strip().lower(),
                    UserFavorite.entity_id == entity_id.strip(),
                )
        else:
            return False

        res = await db.execute(stmt)
        await db.commit()
        return (res.rowcount or 0) > 0

    @staticmethod
    async def save_match(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        match_id: str,
        target_outcome: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> UserSavedMatch:
        if not user_id and not anonymous_session_id:
            raise ValueError("Either user_id or anonymous_session_id must be provided")

        clean_match_id = match_id.strip()

        # Check existing
        if user_id:
            stmt = select(UserSavedMatch).where(
                UserSavedMatch.user_id == user_id,
                UserSavedMatch.match_id == clean_match_id,
            )
        else:
            stmt = select(UserSavedMatch).where(
                UserSavedMatch.anonymous_session_id == anonymous_session_id,
                UserSavedMatch.match_id == clean_match_id,
            )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            if target_outcome is not None:
                existing.target_outcome = target_outcome
            if notes is not None:
                existing.notes = notes
            await db.commit()
            await db.refresh(existing)
            return existing

        saved = UserSavedMatch(
            id=str(uuid.uuid4()),
            user_id=user_id,
            anonymous_session_id=anonymous_session_id if not user_id else None,
            match_id=clean_match_id,
            target_outcome=target_outcome,
            notes=notes,
            created_at=_naive_utc_now(),
        )
        db.add(saved)
        await db.commit()
        await db.refresh(saved)
        return saved

    @staticmethod
    async def get_saved_matches(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
    ) -> List[UserSavedMatch]:
        if not user_id and not anonymous_session_id:
            return []

        if user_id:
            stmt = select(UserSavedMatch).where(UserSavedMatch.user_id == user_id)
        else:
            stmt = select(UserSavedMatch).where(
                UserSavedMatch.anonymous_session_id == anonymous_session_id
            )
        stmt = stmt.order_by(UserSavedMatch.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def remove_saved_match(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        match_id: Optional[str] = None,
        saved_id: Optional[str] = None,
    ) -> bool:
        if not user_id and not anonymous_session_id:
            return False

        if saved_id:
            if user_id:
                stmt = delete(UserSavedMatch).where(
                    UserSavedMatch.id == saved_id,
                    UserSavedMatch.user_id == user_id,
                )
            else:
                stmt = delete(UserSavedMatch).where(
                    UserSavedMatch.id == saved_id,
                    UserSavedMatch.anonymous_session_id == anonymous_session_id,
                )
        elif match_id:
            if user_id:
                stmt = delete(UserSavedMatch).where(
                    UserSavedMatch.user_id == user_id,
                    UserSavedMatch.match_id == match_id.strip(),
                )
            else:
                stmt = delete(UserSavedMatch).where(
                    UserSavedMatch.anonymous_session_id == anonymous_session_id,
                    UserSavedMatch.match_id == match_id.strip(),
                )
        else:
            return False

        res = await db.execute(stmt)
        await db.commit()
        return (res.rowcount or 0) > 0

    @staticmethod
    async def get_preferences(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
    ) -> UserPreference:
        if not user_id and not anonymous_session_id:
            # Return transient default
            return UserPreference(
                id="default",
                user_id=None,
                anonymous_session_id=None,
                odds_format="DECIMAL",
                timezone="Africa/Lagos",
                default_league="EPL",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        if user_id:
            stmt = select(UserPreference).where(UserPreference.user_id == user_id)
        else:
            stmt = select(UserPreference).where(
                UserPreference.anonymous_session_id == anonymous_session_id
            )
        result = await db.execute(stmt)
        pref = result.scalar_one_or_none()
        if pref:
            return pref

        # Create default preference record
        now = _naive_utc_now()
        new_pref = UserPreference(
            id=str(uuid.uuid4()),
            user_id=user_id,
            anonymous_session_id=anonymous_session_id if not user_id else None,
            odds_format="DECIMAL",
            timezone="Africa/Lagos",
            default_league="EPL",
            created_at=now,
            updated_at=now,
        )
        db.add(new_pref)
        await db.commit()
        await db.refresh(new_pref)
        return new_pref

    @staticmethod
    async def update_preferences(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        odds_format: Optional[str] = None,
        timezone_pref: Optional[str] = None,
        default_league: Optional[str] = None,
    ) -> UserPreference:
        pref = await UserStateService.get_preferences(
            db, user_id=user_id, anonymous_session_id=anonymous_session_id
        )
        if pref.id == "default":
            now = _naive_utc_now()
            pref = UserPreference(
                id=str(uuid.uuid4()),
                user_id=user_id,
                anonymous_session_id=anonymous_session_id if not user_id else None,
                odds_format=odds_format or "DECIMAL",
                timezone=timezone_pref or "Africa/Lagos",
                default_league=default_league or "EPL",
                created_at=now,
                updated_at=now,
            )
            db.add(pref)
        else:
            if odds_format is not None:
                pref.odds_format = odds_format
            if timezone_pref is not None:
                pref.timezone = timezone_pref
            if default_league is not None:
                pref.default_league = default_league
            pref.updated_at = _naive_utc_now()

        await db.commit()
        await db.refresh(pref)
        return pref

    @staticmethod
    async def merge_anonymous_state(
        db: AsyncSession, *, user_id: str, anonymous_session_id: str
    ) -> dict[str, Any]:
        """Merge anonymous favorites, saved matches, preferences, and subscriptions into user account."""
        if not user_id or not anonymous_session_id:
            return {"status": "NOOP", "merged_favorites": 0, "merged_saved_matches": 0}

        # 1. Merge Favorites
        anon_favs_res = await db.execute(
            select(UserFavorite).where(
                UserFavorite.anonymous_session_id == anonymous_session_id
            )
        )
        anon_favs = list(anon_favs_res.scalars().all())

        user_favs_res = await db.execute(
            select(UserFavorite).where(UserFavorite.user_id == user_id)
        )
        user_fav_keys = {
            (f.entity_type, f.entity_id) for f in user_favs_res.scalars().all()
        }

        merged_favorites_count = 0
        for fav in anon_favs:
            key = (fav.entity_type, fav.entity_id)
            if key in user_fav_keys:
                await db.delete(fav)
            else:
                fav.user_id = user_id
                fav.anonymous_session_id = None
                user_fav_keys.add(key)
                merged_favorites_count += 1

        # 2. Merge Saved Matches
        anon_matches_res = await db.execute(
            select(UserSavedMatch).where(
                UserSavedMatch.anonymous_session_id == anonymous_session_id
            )
        )
        anon_matches = list(anon_matches_res.scalars().all())

        user_matches_res = await db.execute(
            select(UserSavedMatch).where(UserSavedMatch.user_id == user_id)
        )
        user_match_ids = {m.match_id for m in user_matches_res.scalars().all()}

        merged_saved_count = 0
        for match in anon_matches:
            if match.match_id in user_match_ids:
                await db.delete(match)
            else:
                match.user_id = user_id
                match.anonymous_session_id = None
                user_match_ids.add(match.match_id)
                merged_saved_count += 1

        # 3. Merge Preferences
        anon_pref_res = await db.execute(
            select(UserPreference).where(
                UserPreference.anonymous_session_id == anonymous_session_id
            )
        )
        anon_pref = anon_pref_res.scalar_one_or_none()

        user_pref_res = await db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        user_pref = user_pref_res.scalar_one_or_none()

        if anon_pref:
            if not user_pref:
                anon_pref.user_id = user_id
                anon_pref.anonymous_session_id = None
            else:
                await db.delete(anon_pref)

        # 4. Merge Subscriptions & Notifications
        await db.execute(
            update(UserNotificationSubscription)
            .where(
                UserNotificationSubscription.anonymous_session_id == anonymous_session_id
            )
            .values(user_id=user_id, anonymous_session_id=None)
        )

        await db.execute(
            update(UserNotificationLog)
            .where(UserNotificationLog.anonymous_session_id == anonymous_session_id)
            .values(user_id=user_id, anonymous_session_id=None)
        )

        await db.commit()

        return {
            "status": "MERGED",
            "user_id": user_id,
            "anonymous_session_id": anonymous_session_id,
            "merged_favorites": merged_favorites_count,
            "merged_saved_matches": merged_saved_count,
        }
