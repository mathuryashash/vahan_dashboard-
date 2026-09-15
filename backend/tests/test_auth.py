"""Tests for the access-hierarchy system: login, token verification, and
role enforcement. The `client` fixture defaults to a stub admin override
(see conftest.py) so most of the app's tests don't need a login step --
these tests specifically clear that override to exercise the real
get_current_user/require_role behavior."""
from app.core.auth import get_current_user, hash_password
from app.main import app
from app.models.models import User, UserRole


def _restore_admin_override():
    app.dependency_overrides[get_current_user] = lambda: User(
        id=0, email="test-admin@example.com", role=UserRole.ADMIN, is_active=True
    )


async def _seed_user(db_session, email="viewer@example.com", password="hunter2", role=UserRole.VIEWER):
    user = User(email=email, hashed_password=hash_password(password), full_name="Test User", role=role)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def test_login_with_correct_credentials_returns_a_token(client, db_session):
    await _seed_user(db_session, email="admin@example.com", password="correct-horse", role=UserRole.ADMIN)

    response = await client.post(
        "/api/v1/auth/login", data={"username": "admin@example.com", "password": "correct-horse"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == UserRole.ADMIN
    assert "access_token" not in data  # issued as an httpOnly cookie, not in the body
    assert response.cookies.get("access_token")


async def test_login_with_wrong_password_is_rejected(client, db_session):
    await _seed_user(db_session, email="admin@example.com", password="correct-horse")

    response = await client.post(
        "/api/v1/auth/login", data={"username": "admin@example.com", "password": "wrong"}
    )
    assert response.status_code == 401


async def test_login_with_unknown_email_is_rejected(client, db_session):
    response = await client.post(
        "/api/v1/auth/login", data={"username": "nobody@example.com", "password": "whatever"}
    )
    assert response.status_code == 401


async def test_protected_endpoint_rejects_missing_token(client, db_session):
    # Clear the fixture's default admin override to exercise the real
    # get_current_user dependency instead.
    del app.dependency_overrides[get_current_user]
    try:
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401
    finally:
        _restore_admin_override()


async def test_protected_endpoint_accepts_a_real_token(client, db_session):
    await _seed_user(db_session, email="analyst@example.com", password="pw123456", role=UserRole.ANALYST)
    del app.dependency_overrides[get_current_user]
    try:
        await client.post(
            "/api/v1/auth/login", data={"username": "analyst@example.com", "password": "pw123456"}
        )
        # No manual header needed -- the AsyncClient fixture persists the
        # Set-Cookie from login and resends it automatically, same as a
        # real browser would.
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "analyst@example.com"
        assert data["role"] == UserRole.ANALYST
    finally:
        _restore_admin_override()


async def test_logout_clears_the_session_cookie(client, db_session):
    await _seed_user(db_session, email="logout@example.com", password="pw123456")
    del app.dependency_overrides[get_current_user]
    try:
        await client.post(
            "/api/v1/auth/login", data={"username": "logout@example.com", "password": "pw123456"}
        )
        assert (await client.get("/api/v1/auth/me")).status_code == 200

        logout_response = await client.post("/api/v1/auth/logout")
        assert logout_response.status_code == 200

        assert (await client.get("/api/v1/auth/me")).status_code == 401
    finally:
        _restore_admin_override()


async def test_admin_only_endpoint_rejects_a_viewer_token(client, db_session):
    """Regression-style check for the actual hierarchy enforcement: a real
    logged-in Viewer must not be able to reach an admin-only action."""
    await _seed_user(db_session, email="viewer@example.com", password="pw123456", role=UserRole.VIEWER)
    del app.dependency_overrides[get_current_user]
    try:
        await client.post(
            "/api/v1/auth/login", data={"username": "viewer@example.com", "password": "pw123456"}
        )
        response = await client.get("/api/v1/users/")
        assert response.status_code == 403
    finally:
        _restore_admin_override()


async def test_login_locks_out_after_repeated_failures(client, db_session):
    """Guards against unlimited online password guessing (see
    app/core/rate_limit.py) -- the correct password must still be rejected
    once the failure count trips the lockout, not just wrong ones."""
    await _seed_user(db_session, email="locktarget@example.com", password="correct-horse")
    del app.dependency_overrides[get_current_user]
    try:
        for _ in range(5):
            response = await client.post(
                "/api/v1/auth/login", data={"username": "locktarget@example.com", "password": "wrong"}
            )
            assert response.status_code == 401

        response = await client.post(
            "/api/v1/auth/login", data={"username": "locktarget@example.com", "password": "correct-horse"}
        )
        assert response.status_code == 429
    finally:
        _restore_admin_override()


async def test_admin_can_create_and_list_users(client, db_session):
    response = await client.post(
        "/api/v1/users/",
        json={"email": "new@example.com", "password": "pw123456-long-enough", "full_name": "New Person", "role": UserRole.ANALYST},
    )
    assert response.status_code == 200
    assert response.json()["role"] == UserRole.ANALYST

    response = await client.get("/api/v1/users/")
    assert response.status_code == 200
    emails = [u["email"] for u in response.json()]
    assert "new@example.com" in emails


async def test_create_user_rejects_a_too_short_password(client, db_session):
    # 422 from validation, not a created account -- an admin fat-fingering a
    # short password on a customer's login must fail loudly, not silently
    # ship a weak credential.
    response = await client.post(
        "/api/v1/users/", json={"email": "weak@example.com", "password": "short"}
    )
    assert response.status_code == 422


async def test_create_user_rejects_duplicate_email(client, db_session):
    await _seed_user(db_session, email="dupe@example.com")

    response = await client.post(
        "/api/v1/users/", json={"email": "dupe@example.com", "password": "pw123456-long-enough"}
    )
    assert response.status_code == 400


async def test_admin_can_deactivate_a_user(client, db_session):
    user = await _seed_user(db_session, email="toggle@example.com")

    response = await client.patch(f"/api/v1/users/{user.id}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_admin_can_create_organization_and_assign_users_to_it(client, db_session):
    response = await client.post("/api/v1/organizations/", json={"name": "Acme Motors"})
    assert response.status_code == 200
    org = response.json()
    assert org["user_count"] == 0

    response = await client.post(
        "/api/v1/users/",
        json={"email": "acme-user@example.com", "password": "pw123456-long-enough", "organization_id": org["id"]},
    )
    assert response.status_code == 200
    assert response.json()["organization_id"] == org["id"]

    response = await client.get("/api/v1/organizations/")
    assert response.status_code == 200
    acme = next(o for o in response.json() if o["id"] == org["id"])
    assert acme["user_count"] == 1


async def test_create_user_rejects_unknown_organization_id(client, db_session):
    response = await client.post(
        "/api/v1/users/",
        json={"email": "orphan@example.com", "password": "pw123456-long-enough", "organization_id": 999999},
    )
    assert response.status_code == 400


async def test_create_organization_rejects_duplicate_name(client, db_session):
    await client.post("/api/v1/organizations/", json={"name": "Duplicate Co"})
    response = await client.post("/api/v1/organizations/", json={"name": "Duplicate Co"})
    assert response.status_code == 400
