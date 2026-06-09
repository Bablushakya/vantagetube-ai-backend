"""
app/api/settings.py — User settings GET/PUT
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.core.security import get_current_user, verify_password, hash_password
from app.core.supabase_client import get_supabase

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    email_notifications: Optional[bool] = None
    weekly_digest:       Optional[bool] = None
    generation_alerts:   Optional[bool] = None
    theme:               Optional[str]  = None
    language:            Optional[str]  = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("")
async def get_settings(current_user: dict = Depends(get_current_user)):
    db  = get_supabase()
    try:
        result = db.table("user_settings").select("*").eq("user_id", current_user["id"]).limit(1).execute()
        data = result.data if hasattr(result, "data") else None
        row = data[0] if isinstance(data, list) and len(data) > 0 else None
    except Exception:
        row = None
    if row:
        return row
    # Return defaults
    return {
        "email_notifications": True,
        "weekly_digest":       True,
        "generation_alerts":   False,
        "theme":               "dark",
        "language":            "en",
    }


@router.put("")
async def update_settings(payload: SettingsUpdateRequest, current_user: dict = Depends(get_current_user)):
    db      = get_supabase()
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    updates["user_id"] = current_user["id"]
    db.table("user_settings").upsert(updates, on_conflict="user_id").execute()
    return {"message": "Settings saved"}


@router.post("/change-password")
async def change_password(payload: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    db = get_supabase()
    
    # Verify current password
    result = db.table("users").select("password_hash").eq("id", current_user["id"]).limit(1).execute()
    data = result.data if hasattr(result, "data") else None
    user_row = data[0] if isinstance(data, list) and len(data) > 0 else None
    
    if not user_row or not verify_password(payload.current_password, user_row.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Incorrect current password")
        
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
        
    # Update password
    db.table("users").update({"password_hash": hash_password(payload.new_password)}).eq("id", current_user["id"]).execute()
    return {"message": "Password updated successfully"}
