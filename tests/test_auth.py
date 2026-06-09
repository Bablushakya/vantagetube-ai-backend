"""
tests/test_auth.py — Authentication & core endpoint tests
VantageTube AI
"""
import pytest
import warnings
import os

# ── Suppress supabase-py deprecation warnings in tests ────
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── Set dummy env vars BEFORE importing app ────────────────
os.environ.setdefault("SUPABASE_URL",              "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY",         "test_anon_key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test_service_key")
os.environ.setdefault("JWT_SECRET_KEY",            "test_secret_key_at_least_32_chars_long!")
os.environ.setdefault("GEMINI_API_KEY",            "")
os.environ.setdefault("GOOGLE_CLIENT_ID",          "")
os.environ.setdefault("GOOGLE_CLIENT_SECRET",      "")

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Patch supabase init before app import
with patch("app.core.supabase_client.create_client", return_value=MagicMock()):
    from main import app

client = TestClient(app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════
# Health Check
# ══════════════════════════════════════════════════════════
class TestHealth:
    def test_health_ok(self):
        res = client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_docs_accessible(self):
        res = client.get("/api/docs")
        assert res.status_code == 200


# ══════════════════════════════════════════════════════════
# Auth — Register
# ══════════════════════════════════════════════════════════
class TestRegister:
    def test_missing_password(self):
        res = client.post("/api/auth/register", json={"email": "test@test.com"})
        assert res.status_code == 422

    def test_short_password(self):
        res = client.post("/api/auth/register", json={
            "email": "test@test.com", "password": "short"
        })
        assert res.status_code == 422

    def test_invalid_email(self):
        res = client.post("/api/auth/register", json={
            "email": "not-an-email", "password": "Password123!"
        })
        assert res.status_code == 422

    @patch("app.api.auth.hash_password", return_value="$2b$12$mockedhashvalue1234567890123456")
    @patch("app.api.auth.get_supabase")
    def test_register_success(self, mock_db, mock_hash):
        mock = MagicMock()
        mock_db.return_value = mock
        # Simulate: no existing user with this email
        mock.table().select().eq().execute.return_value.data = []
        # Simulate: insert returns new user row
        mock.table().insert().execute.return_value.data = [{
            "id": "usr_001", "email": "new@test.com", "full_name": "Test User",
            "plan": "free", "created_at": "2024-01-01T00:00:00Z",
            "avatar_url": None,
        }]
        res = client.post("/api/auth/register", json={
            "email": "new@test.com", "password": "Password123!", "full_name": "Test User"
        })
        assert res.status_code == 201
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "new@test.com"

    @patch("app.api.auth.get_supabase")
    def test_register_duplicate_email(self, mock_db):
        mock = MagicMock()
        mock_db.return_value = mock
        # Email already exists
        mock.table().select().eq().execute.return_value.data = [{"id": "existing"}]
        res = client.post("/api/auth/register", json={
            "email": "existing@test.com", "password": "Password123!"
        })
        assert res.status_code == 400


# ══════════════════════════════════════════════════════════
# Auth — Login
# ══════════════════════════════════════════════════════════
class TestLogin:
    def test_missing_password(self):
        res = client.post("/api/auth/login", json={"email": "test@test.com"})
        assert res.status_code == 422

    def test_missing_email(self):
        res = client.post("/api/auth/login", json={"password": "Password123!"})
        assert res.status_code == 422

    @patch("app.api.auth.get_supabase")
    def test_user_not_found(self, mock_db):
        mock = MagicMock()
        mock_db.return_value = mock
        mock.table().select().eq().maybe_single().execute.return_value.data = None
        res = client.post("/api/auth/login", json={
            "email": "nobody@test.com", "password": "Password123!"
        })
        assert res.status_code == 401

    @patch("app.api.auth.verify_password", return_value=False)
    @patch("app.api.auth.get_supabase")
    def test_wrong_password(self, mock_db, mock_verify):
        mock = MagicMock()
        mock_db.return_value = mock
        mock.table().select().eq().maybe_single().execute.return_value.data = {
            "id": "usr_001", "email": "test@test.com",
            "password_hash": "$2b$12$somerealhashvalue12345678",
        }
        res = client.post("/api/auth/login", json={
            "email": "test@test.com", "password": "wrongpassword"
        })
        assert res.status_code == 401


# ══════════════════════════════════════════════════════════
# Protected Routes — No Token
# ══════════════════════════════════════════════════════════
class TestProtectedRoutes:
    """All protected endpoints must return 403 without a token."""

    def test_me_no_auth(self):
        assert client.get("/api/auth/me").status_code == 403

    def test_profile_no_auth(self):
        assert client.get("/api/profile").status_code == 403

    def test_settings_no_auth(self):
        assert client.get("/api/settings").status_code == 403

    def test_channel_no_auth(self):
        assert client.get("/api/youtube/channel").status_code == 403

    def test_videos_no_auth(self):
        assert client.get("/api/youtube/videos").status_code == 403

    def test_trending_no_auth(self):
        assert client.get("/api/trending").status_code == 403

    def test_generate_title_no_auth(self):
        assert client.post("/api/ai/generate-title", json={"keywords": "AI"}).status_code == 403

    def test_generate_description_no_auth(self):
        assert client.post("/api/ai/generate-description", json={"title": "Test"}).status_code == 403

    def test_generate_tags_no_auth(self):
        assert client.post("/api/ai/generate-tags", json={"title": "Test"}).status_code == 403

    def test_generate_thumbnail_no_auth(self):
        assert client.post("/api/ai/generate-thumbnail", json={"title": "Test"}).status_code == 403


# ══════════════════════════════════════════════════════════
# Token Refresh
# ══════════════════════════════════════════════════════════
class TestTokenRefresh:
    def test_invalid_token(self):
        res = client.post("/api/auth/refresh", json={"refresh_token": "invalid.token"})
        assert res.status_code in [401, 422]

    def test_empty_token(self):
        res = client.post("/api/auth/refresh", json={"refresh_token": ""})
        assert res.status_code in [401, 422]


# ══════════════════════════════════════════════════════════
# Input Validation
# ══════════════════════════════════════════════════════════
class TestValidation:
    def test_ai_title_empty_keywords(self):
        # Needs auth, so just testing schema validation
        res = client.post("/api/ai/generate-title", json={})
        assert res.status_code in [403, 422]

    def test_settings_bad_method(self):
        res = client.delete("/api/settings")
        assert res.status_code in [403, 405]
