from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import get_settings
from app.services import oidc
from tests.conftest import login
from tests.fake_idp import FakeIdP


@pytest.fixture(scope="module")
def idp():
    server = FakeIdP()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def sso_env(idp, monkeypatch):
    def configure(**extra):
        env = {
            "OIDC_ISSUER_URL": idp.issuer,
            "OIDC_CLIENT_ID": idp.client_id,
            "OIDC_CLIENT_SECRET": idp.client_secret,
            "OIDC_DISPLAY_NAME": "authentik",
            **{k.upper(): str(v) for k, v in extra.items()},
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        oidc.reset_client()

    configure()
    yield configure
    for k in ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_DISPLAY_NAME",
              "OIDC_ADMIN_GROUP", "OIDC_LINK_EXISTING_USERS", "PASSWORD_LOGIN"):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    oidc.reset_client()


def sso_login(client, idp, user: dict):
    """Run the full browser round trip: app -> IdP -> app callback. Returns the final response."""
    idp.next_user = user
    start = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert start.status_code in (302, 303, 307), start.text
    assert start.headers["location"].startswith(idp.issuer)
    at_idp = httpx.get(start.headers["location"], follow_redirects=False)
    assert at_idp.status_code == 302
    back = urlparse(at_idp.headers["location"])
    assert back.path == "/api/auth/oidc/callback"
    return client.get(f"{back.path}?{back.query}", follow_redirects=False)


def test_config_advertises_sso(client, sso_env):
    cfg = client.get("/api/auth/config").json()
    assert cfg["oidc_enabled"] is True
    assert cfg["oidc_display_name"] == "authentik"
    assert cfg["password_login"] is True


def test_sso_disabled_by_default(client):
    assert client.get("/api/auth/config").json()["oidc_enabled"] is False
    assert client.get("/api/auth/oidc/login", follow_redirects=False).status_code == 404


def test_full_login_creates_user(client, idp, sso_env):
    r = sso_login(client, idp, {"sub": "abc-123", "preferred_username": "Bob Smith", "email": "bob@example.com"})
    assert r.status_code == 303 and r.headers["location"] == "/"
    me = client.get("/api/auth/me").json()
    assert me["username"] == "Bob_Smith"
    assert me["sso"] is True and me["has_password"] is False
    assert me["is_admin"] is False  # the env admin already exists, so this is not the first user
    # The new user got default categories and an account, and can use the API with CSRF.
    client.headers["X-CSRF-Token"] = client.cookies.get("ft_csrf")
    assert len(client.get("/api/accounts").json()) == 1
    assert client.post("/api/categories", json={"name": "Hobby"}).status_code == 201
    # SSO users have no local password.
    assert client.post("/api/auth/password", json={"current_password": "", "new_password": "whatever1"}).status_code == 400

    # Logging in again maps to the same user, even after a rename at the provider.
    client.post("/api/auth/logout")
    sso_login(client, idp, {"sub": "abc-123", "preferred_username": "bobby"})
    assert client.get("/api/auth/me").json()["id"] == me["id"]


def test_admin_group_sync(client, idp, sso_env):
    sso_env(oidc_admin_group="ledger-admins")
    sso_login(client, idp, {"sub": "adm-1", "preferred_username": "carol", "groups": ["users", "ledger-admins"]})
    assert client.get("/api/auth/me").json()["is_admin"] is True
    client.cookies.clear()
    sso_login(client, idp, {"sub": "adm-1", "preferred_username": "carol", "groups": ["users"]})
    assert client.get("/api/auth/me").json()["is_admin"] is False


def test_username_collision_and_linking(client, idp, sso_env):
    # A local "admin" exists (created from env). Without linking, SSO "admin" gets a new account.
    sso_login(client, idp, {"sub": "x-1", "preferred_username": "admin"})
    assert client.get("/api/auth/me").json()["username"] == "admin-2"
    client.cookies.clear()

    sso_env(oidc_link_existing_users="true")
    sso_login(client, idp, {"sub": "x-2", "preferred_username": "admin"})
    me = client.get("/api/auth/me").json()
    assert me["username"] == "admin" and me["is_admin"] is True and me["sso"] is True
    assert me["has_password"] is True  # the local password still works as a fallback


def test_deactivated_user_is_refused(client, idp, sso_env):
    admin = login(client, "admin", "admin-password")
    sso_login(admin, idp, {"sub": "d-1", "preferred_username": "dave"})
    admin.cookies.clear()
    login(admin, "admin", "admin-password")
    dave = next(u for u in admin.get("/api/admin/users").json() if u["username"] == "dave")
    assert dave["sso"] is True
    admin.patch(f"/api/admin/users/{dave['id']}", json={"is_active": False})
    admin.cookies.clear()
    r = sso_login(admin, idp, {"sub": "d-1", "preferred_username": "dave"})
    assert r.status_code == 303 and "sso_error=" in r.headers["location"]
    assert "deactivated" in parse_qs(urlparse(r.headers["location"]).query)["sso_error"][0]


def test_tampered_state_is_rejected(client, idp, sso_env):
    idp.next_user = {"sub": "t-1", "preferred_username": "mallory"}
    start = client.get("/api/auth/oidc/login", follow_redirects=False)
    at_idp = httpx.get(start.headers["location"], follow_redirects=False)
    back = urlparse(at_idp.headers["location"])
    q = parse_qs(back.query)
    r = client.get(f"{back.path}?code={q['code'][0]}&state=forged", follow_redirects=False)
    assert "sso_error=" in r.headers["location"]
    assert client.get("/api/auth/me").status_code == 401


def test_password_login_can_be_disabled(client, sso_env):
    sso_env(password_login="false")
    assert client.get("/api/auth/config").json()["password_login"] is False
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin-password"})
    assert r.status_code == 403


def test_unreachable_provider_shows_error(client, monkeypatch, sso_env):
    sso_env(oidc_issuer_url="http://127.0.0.1:9/nowhere/")
    r = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 303 and "sso_error=" in r.headers["location"]
