"""
app/services/auth_service.py
"""
import httpx
import datetime
import urllib.parse
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.core.supabase_client import get_supabase


class AuthService:
    def issue_tokens(self, user: dict) -> dict:
        user_id = str(user["id"])
        access  = create_access_token({"sub": user_id})
        refresh = create_refresh_token({"sub": user_id})
        return {"access_token": access, "refresh_token": refresh}

    def safe_user(self, user: dict) -> dict:
        """Strip sensitive fields before returning to client."""
        return {
            "id":         user.get("id"),
            "email":      user.get("email"),
            "full_name":  user.get("full_name", ""),
            "avatar_url": user.get("avatar_url"),
            "plan":       user.get("plan", "free"),
            "created_at": user.get("created_at"),
        }

    def google_oauth_url(self, state: str = "") -> str:
        """
        Google OAuth URL for sign-in (openid + profile + YouTube scopes).
        state="" → login/register flow → redirects to auth-callback.html
        state="youtube:<user_id>" → YouTube connect flow → redirects to oauth-callback.html
        """
        scopes = " ".join([
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ])
        params = {
            "client_id":     settings.GOOGLE_CLIENT_ID,
            "redirect_uri":  f"{settings.BACKEND_URL}/api/auth/google/callback",
            "response_type": "code",
            "scope":         scopes,
            "access_type":   "offline",
            "prompt":        "consent",
        }
        if state:
            params["state"] = state
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

    def youtube_connect_url(self, user_id: str) -> str:
        """OAuth URL specifically for connecting a YouTube channel to an existing account."""
        return self.google_oauth_url(state=f"youtube:{user_id}")

    async def handle_google_callback(self, code: str, state: str = "") -> dict:
        """
        Exchange OAuth code for Google tokens, upsert user in Supabase.
        Returns the user dict.
        """
        async with httpx.AsyncClient() as client:
            token_res = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code":          code,
                    "client_id":     settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri":  f"{settings.BACKEND_URL}/api/auth/google/callback",
                    "grant_type":    "authorization_code",
                },
            )
            token_res.raise_for_status()
            token_data = token_res.json()

            userinfo_res = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            userinfo_res.raise_for_status()
            userinfo = userinfo_res.json()

        db    = get_supabase()
        email = userinfo.get("email")

        # If this is a YouTube connect flow, use the existing user from state
        if state.startswith("youtube:"):
            user_id = state.split(":", 1)[1]
            result  = db.table("users").select("*").eq("id", user_id).maybe_single().execute()
            user    = result.data if result.data else None
            if not user:
                # Fallback: upsert by email
                user = await self._upsert_user_by_email(db, userinfo)
        else:
            user = await self._upsert_user_by_email(db, userinfo)

        # Store OAuth tokens
        expires_in = token_data.get("expires_in", 3600)
        expires_at = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=expires_in)
        ).isoformat()

        db.table("user_oauth_tokens").upsert({
            "user_id":       user["id"],
            "access_token":  token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token", ""),
            "scope":         token_data.get("scope", ""),
            "expires_at":    expires_at,
        }, on_conflict="user_id").execute()

        return user

    async def _upsert_user_by_email(self, db, userinfo: dict) -> dict:
        email    = userinfo.get("email")
        try:
            existing_row = db.table("users").select("*").eq("email", email).maybe_single().execute()
            existing_data = existing_row.data if existing_row is not None else None
        except Exception:
            existing_data = None

        if existing_data:
            user = db.table("users").update({
                "full_name":  userinfo.get("name", ""),
                "avatar_url": userinfo.get("picture"),
                "google_id":  userinfo.get("sub"),
            }).eq("id", existing_data["id"]).execute().data[0]
        else:
            user = db.table("users").insert({
                "email":         email,
                "full_name":     userinfo.get("name", ""),
                "avatar_url":    userinfo.get("picture"),
                "google_id":     userinfo.get("sub"),
                "password_hash": "",
                "plan":          "free",
            }).execute().data[0]
        return user
