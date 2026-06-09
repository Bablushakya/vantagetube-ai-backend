"""
app/api/auth.py — Authentication endpoints

POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
POST /api/auth/refresh
GET  /api/auth/google
GET  /api/auth/google/callback

OAuth state routing:
  state=""              → Google sign-in/register → auth-callback.html
  state="youtube:<uid>" → YouTube channel connect → oauth-callback.html
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse

from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, RefreshRequest
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user,
)
from app.core.supabase_client import get_supabase
from app.core.config import settings
from app.services.auth_service import AuthService

logger = logging.getLogger("vantagetube")
router   = APIRouter()
auth_svc = AuthService()


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest):
    """Create new account with email + password."""
    db = get_supabase()

    existing = db.table("users").select("id").eq("email", payload.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = db.table("users").insert({
        "email":         payload.email,
        "password_hash": hash_password(payload.password),
        "full_name":     payload.full_name,
        "plan":          "free",
    }).execute().data[0]

    tokens = auth_svc.issue_tokens(user)
    return {**tokens, "user": auth_svc.safe_user(user)}


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    """Sign in with email + password."""
    db     = get_supabase()
    result = db.table("users").select("*").eq("email", payload.email).maybe_single().execute()

    if not result.data or not verify_password(payload.password, result.data.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    tokens = auth_svc.issue_tokens(result.data)
    return {**tokens, "user": auth_svc.safe_user(result.data)}


@router.post("/logout", status_code=204)
async def logout(current_user: dict = Depends(get_current_user)):
    """Stateless JWT — client discards tokens."""
    return None


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    """Return current authenticated user."""
    return auth_svc.safe_user(current_user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    """Issue new access token from refresh token."""
    try:
        decoded = decode_token(payload.refresh_token)
        if decoded.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Not a refresh token")
        user_id = decoded.get("sub")
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    db     = get_supabase()
    result = db.table("users").select("*").eq("id", user_id).maybe_single().execute()
    if not result.data:
        raise HTTPException(status_code=401, detail="User not found")

    tokens = auth_svc.issue_tokens(result.data)
    return {**tokens, "user": auth_svc.safe_user(result.data)}


@router.get("/google")
async def google_auth_url():
    """Return Google OAuth2 authorization URL for sign-in."""
    return {"auth_url": auth_svc.google_oauth_url()}


@router.get("/google/callback")
async def google_callback(code: str = Query(...), state: str = Query("")):
    """
    Handle Google OAuth callback.

    Two flows based on state:
      - state=""              → Google login/register → redirect to auth-callback.html
      - state="youtube:<uid>" → YouTube channel connect → fetch channel data → redirect to oauth-callback.html
    """
    try:
        user = await auth_svc.handle_google_callback(code, state)
    except Exception as e:
        logger.error(f"Google callback error: {e}")
        error_msg = str(e).replace('"', "'")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/pages/auth-callback.html?error={error_msg}"
        )

    # ── YouTube connect flow ──────────────────────────────
    if state.startswith("youtube:"):
        # Fetch and cache channel data immediately after connecting
        from app.services.youtube_service import YouTubeService
        yt_svc = YouTubeService()
        channel_name    = ""
        subscriber_count = 0
        try:
            ch = await yt_svc.get_channel(user["id"])
            channel_name     = ch.get("channel_name", "")
            subscriber_count = ch.get("subscriber_count", 0)
            # Also trigger initial video sync in background (best-effort)
            try:
                await yt_svc.sync_videos(user["id"])
            except Exception as sync_err:
                logger.warning(f"Initial video sync failed (non-fatal): {sync_err}")
        except Exception as ch_err:
            logger.warning(f"Channel fetch after connect failed (non-fatal): {ch_err}")

        redirect_url = (
            f"{settings.FRONTEND_URL}/pages/oauth-callback.html"
            f"?connected=true"
            f"&channel_name={channel_name}"
            f"&subscriber_count={subscriber_count}"
        )
        return RedirectResponse(url=redirect_url)

    # ── Google sign-in / register flow ───────────────────
    tokens = auth_svc.issue_tokens(user)
    redirect_url = (
        f"{settings.FRONTEND_URL}/pages/auth-callback.html"
        f"?access_token={tokens['access_token']}"
        f"&refresh_token={tokens['refresh_token']}"
    )
    return RedirectResponse(url=redirect_url)
