"""Unit tests for auth endpoints, anonymous session tracking, and user state merging."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.database import UserAccount
from src.core.security import get_password_hash
from src.db.models import UserFavorite, UserSavedMatch
from src.services.auth_service import UserStateService, _naive_utc_now


@pytest.mark.asyncio
async def test_user_state_service_favorites_crud() -> None:
    db = AsyncMock()
    db.add = MagicMock()

    # Mock empty select
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = scalar_mock

    # Add favorite
    fav = await UserStateService.add_favorite(
        db, user_id="user-1", entity_type="team", entity_id="arsenal"
    )
    assert fav.user_id == "user-1"
    assert fav.entity_type == "team"
    assert fav.entity_id == "arsenal"
    # Regression: UserFavorite.created_at is a naive `DateTime` column — a
    # tz-aware value here crashes asyncpg at bind time ("can't subtract
    # offset-naive and offset-aware datetimes").
    assert fav.created_at.tzinfo is None
    db.add.assert_called_once()
    db.commit.assert_awaited()

    # Get favorites
    scalars_mock = MagicMock()
    scalars_mock.scalars.return_value.all.return_value = [fav]
    db.execute.return_value = scalars_mock

    favs = await UserStateService.get_favorites(db, user_id="user-1")
    assert len(favs) == 1
    assert favs[0].entity_id == "arsenal"

    # Remove favorite
    db.execute.return_value = MagicMock(rowcount=1)
    removed = await UserStateService.remove_favorite(
        db, user_id="user-1", entity_type="team", entity_id="arsenal"
    )
    assert removed is True


@pytest.mark.asyncio
async def test_user_state_service_saved_matches_crud() -> None:
    db = AsyncMock()
    db.add = MagicMock()

    # Mock empty select
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = scalar_mock

    saved = await UserStateService.save_match(
        db,
        anonymous_session_id="anon-99",
        match_id="fd-12345",
        target_outcome="HOME_WIN",
        notes="High value edge",
    )
    assert saved.anonymous_session_id == "anon-99"
    assert saved.match_id == "fd-12345"
    assert saved.target_outcome == "HOME_WIN"
    # Regression: same naive-column requirement as UserFavorite.created_at.
    assert saved.created_at.tzinfo is None

    # Get saved matches
    scalars_mock = MagicMock()
    scalars_mock.scalars.return_value.all.return_value = [saved]
    db.execute.return_value = scalars_mock

    matches = await UserStateService.get_saved_matches(
        db, anonymous_session_id="anon-99"
    )
    assert len(matches) == 1
    assert matches[0].match_id == "fd-12345"

    # Remove match
    db.execute.return_value = MagicMock(rowcount=1)
    removed = await UserStateService.remove_saved_match(
        db, anonymous_session_id="anon-99", match_id="fd-12345"
    )
    assert removed is True


@pytest.mark.asyncio
async def test_user_state_service_merge_anonymous() -> None:
    db = AsyncMock()

    anon_fav = UserFavorite(
        id="f1",
        user_id=None,
        anonymous_session_id="anon-123",
        entity_type="team",
        entity_id="chelsea",
    )
    anon_match = UserSavedMatch(
        id="m1",
        user_id=None,
        anonymous_session_id="anon-123",
        match_id="fd-500",
    )

    # 1. return anon_fav, 2. return empty user_fav, 3. return anon_match, 4. return empty user_match, 5. return None anon_pref, 6. return None user_pref
    call_returns = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: [anon_fav])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [anon_match])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [])),
        MagicMock(scalar_one_or_none=lambda: None),
        MagicMock(scalar_one_or_none=lambda: None),
        MagicMock(rowcount=1),
        MagicMock(rowcount=1),
    ]
    db.execute.side_effect = call_returns

    result = await UserStateService.merge_anonymous_state(
        db, user_id="user-real-1", anonymous_session_id="anon-123"
    )

    assert result["status"] == "MERGED"
    assert result["merged_favorites"] == 1
    assert result["merged_saved_matches"] == 1
    assert anon_fav.user_id == "user-real-1"
    assert anon_fav.anonymous_session_id is None
    assert anon_match.user_id == "user-real-1"
    assert anon_match.anonymous_session_id is None


@pytest.mark.asyncio
async def test_auth_cookie_login_sets_httponly_cookie() -> None:
    from src.db.session import get_async_session

    mock_db = AsyncMock()
    app.dependency_overrides[get_async_session] = lambda: mock_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            mock_user = UserAccount(
                id="user-abc",
                email="test@sabiscore.com",
                full_name="Tester",
                hashed_password=get_password_hash("password123"),
                is_active=True,
                is_superuser=False,
            )

            with patch("src.api.endpoints.auth._get_user_by_email", new=AsyncMock(return_value=mock_user)):
                with patch("src.api.endpoints.auth._touch_last_login", new=AsyncMock()):
                    response = await client.post(
                        "/api/v1/auth/cookie-login",
                        json={"email": "test@sabiscore.com", "password": "password123"},
                    )

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert "sabi_session" in response.cookies
    finally:
        app.dependency_overrides.pop(get_async_session, None)


@pytest.mark.asyncio
async def test_touch_last_login_writes_naive_datetimes() -> None:
    """Regression for the live 500 on POST /api/v1/auth/login.

    UserAccount.last_login_at/updated_at are naive `DateTime` columns.
    `_touch_last_login` used to assign `datetime.now(timezone.utc)` directly,
    which crashes asyncpg at bind time on every real login — but the cookie-
    login test above mocks `_touch_last_login` out entirely, so it never
    exercised the real function. This test calls it directly.
    """
    from src.api.endpoints.auth import _touch_last_login

    db = AsyncMock()
    user = UserAccount(
        id="user-1",
        email="test@sabiscore.com",
        hashed_password="x",
        is_active=True,
    )

    await _touch_last_login(db, user)

    assert user.last_login_at.tzinfo is None
    assert user.updated_at.tzinfo is None
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_get_preferences_creates_naive_default_row() -> None:
    """GET /api/users/preferences auto-creates a default row on first call
    for any user/anon session — the same naive-column bug class as login."""
    db = AsyncMock()
    db.add = MagicMock()
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = scalar_mock

    pref = await UserStateService.get_preferences(db, user_id="user-1")

    assert pref.created_at.tzinfo is None
    assert pref.updated_at.tzinfo is None
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_update_preferences_writes_naive_datetimes() -> None:
    """With a user_id, get_preferences' internal lookup auto-creates a
    persisted row (no existing pref), so update_preferences takes its
    field-update else-branch — exercising the `pref.updated_at = ...` fix."""
    db = AsyncMock()
    db.add = MagicMock()
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = scalar_mock

    pref = await UserStateService.update_preferences(
        db, user_id="user-1", odds_format="FRACTIONAL"
    )

    assert pref.id != "default"
    assert pref.odds_format == "FRACTIONAL"
    assert pref.created_at.tzinfo is None
    assert pref.updated_at.tzinfo is None


@pytest.mark.asyncio
async def test_update_preferences_no_session_creates_naive_default() -> None:
    """With neither user_id nor anonymous_session_id, get_preferences returns
    its transient id="default" object, forcing update_preferences' OWN
    default-creation branch — a distinct fix site from the test above."""
    db = AsyncMock()
    db.add = MagicMock()

    pref = await UserStateService.update_preferences(db, odds_format="AMERICAN")

    assert pref.id != "default"
    assert pref.odds_format == "AMERICAN"
    assert pref.created_at.tzinfo is None
    assert pref.updated_at.tzinfo is None


def test_naive_utc_now_strips_tzinfo() -> None:
    now = _naive_utc_now()
    assert now.tzinfo is None


@pytest.mark.asyncio
async def test_auth_logout_clears_cookie() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        assert response.json() == {"status": "LOGGED_OUT"}
