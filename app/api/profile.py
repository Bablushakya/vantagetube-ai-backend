"""
app/api/profile.py — Profile CRUD
GET/PUT /api/profile
DELETE  /api/profile
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional
from app.core.security import get_current_user
from app.core.supabase_client import get_supabase

router = APIRouter()


class ProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


@router.get("")
async def get_profile(current_user: dict = Depends(get_current_user)):
    db = get_supabase()

    def _safe_data(result):
        """Return result.data[0] if result is a list, else result.data, else None."""
        if result is None:
            return None
        try:
            data = result.data if hasattr(result, "data") else None
            if isinstance(data, list):
                return data[0] if len(data) > 0 else None
            return data
        except Exception:
            return None

    # Channel info
    try:
        ch_result = db.table("youtube_channels").select("channel_name,channel_handle,subscriber_count,connected_at").eq("user_id", current_user["id"]).limit(1).execute()
        ch = _safe_data(ch_result)
    except Exception:
        ch = None

    # Usage
    from datetime import datetime, timezone, date
    today = date.today().isoformat()
    try:
        usage_result = db.table("usage_metrics").select("tokens_used,request_count").eq("user_id", current_user["id"]).eq("date", today).limit(1).execute()
        usage = _safe_data(usage_result) or {"tokens_used": 0, "request_count": 0}
    except Exception:
        usage = {"tokens_used": 0, "request_count": 0}

    # Total generations
    try:
        total_result = db.table("ai_generations").select("id", count="exact").eq("user_id", current_user["id"]).execute()
        total_count = total_result.count if total_result is not None and hasattr(total_result, "count") else 0
    except Exception:
        total_count = 0

    return {
        "user":    {k: current_user.get(k) for k in ["id", "email", "full_name", "avatar_url", "plan", "created_at"]},
        "channel": ch,
        "usage":   {
            "requests_today":    usage.get("request_count", 0),
            "requests_limit":    50,
            "tokens_used_today": usage.get("tokens_used", 0),
            "tokens_limit":      50000,
            "generations_total": total_count or 0,
        },
    }


@router.put("")
async def update_profile(payload: ProfileUpdateRequest, current_user: dict = Depends(get_current_user)):
    db = get_supabase()
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if updates:
        db.table("users").update(updates).eq("id", current_user["id"]).execute()
    return {"message": "Profile updated successfully"}


@router.delete("", status_code=204)
async def delete_account(current_user: dict = Depends(get_current_user)):
    db = get_supabase()
    uid = current_user["id"]
    db.table("ai_generations").delete().eq("user_id", uid).execute()
    db.table("usage_metrics").delete().eq("user_id", uid).execute()
    db.table("user_oauth_tokens").delete().eq("user_id", uid).execute()
    db.table("youtube_channels").delete().eq("user_id", uid).execute()
    db.table("users").delete().eq("id", uid).execute()
    return None
