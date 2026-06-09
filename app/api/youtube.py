"""
app/api/youtube.py — YouTube channel & video endpoints

GET  /api/youtube/status       → {"connected": bool, "channel_name": str|null}
GET  /api/youtube/auth-url     → {"auth_url": str}  (YouTube connect OAuth URL)
GET  /api/youtube/channel      → channel stats (graceful "connected:false" if not linked)
GET  /api/youtube/videos       → paginated videos (from Supabase cache or YouTube)
POST /api/youtube/sync         → force re-sync all videos from YouTube → Supabase
POST /api/youtube/disconnect   → remove OAuth tokens + channel record
"""
from fastapi import APIRouter, Depends, Query
from app.core.security import get_current_user
from app.services.youtube_service import YouTubeService
from app.services.auth_service import AuthService

router = APIRouter()
yt_svc   = YouTubeService()
auth_svc = AuthService()


@router.get("/status")
async def get_status(current_user: dict = Depends(get_current_user)):
    """
    Check if the user has connected their YouTube channel.
    Never throws — safe to call on every page load.
    """
    return await yt_svc.get_status(current_user["id"])


@router.get("/auth-url")
async def get_auth_url(current_user: dict = Depends(get_current_user)):
    """
    Return Google OAuth URL for YouTube channel linking.
    Embeds user_id in state so the callback knows which account to link.
    """
    url = auth_svc.youtube_connect_url(current_user["id"])
    return {"auth_url": url}


@router.get("/channel")
async def get_channel(current_user: dict = Depends(get_current_user)):
    """
    Fetch and cache channel overview data.
    Returns {"connected": false} gracefully when YouTube is not linked.
    """
    return await yt_svc.get_channel(current_user["id"])


@router.get("/videos")
async def get_videos(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, le=50),
    current_user: dict = Depends(get_current_user),
):
    """
    Return paginated videos.
    Serves from Supabase cache; auto-syncs from YouTube if cache is empty.
    """
    return await yt_svc.get_videos(current_user["id"], page, per_page)


@router.post("/sync")
async def sync_videos(current_user: dict = Depends(get_current_user)):
    """
    Force a full re-sync of all videos from YouTube into Supabase.
    Detects new uploads and updates existing video stats.
    Returns {"new": int, "updated": int, "total": int}
    """
    result = await yt_svc.sync_videos(current_user["id"])
    return {"message": "Sync complete", **result}


@router.post("/disconnect", status_code=204)
async def disconnect(current_user: dict = Depends(get_current_user)):
    """Remove OAuth tokens and channel link for the user."""
    await yt_svc.disconnect(current_user["id"])
    return None
