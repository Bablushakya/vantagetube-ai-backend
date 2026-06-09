"""
app/api/api_keys.py — API Keys endpoints
"""
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import get_current_user, hash_password
from app.core.supabase_client import get_supabase

router = APIRouter()

class CreateApiKeyRequest(BaseModel):
    name: str

@router.get("")
async def list_api_keys(current_user: dict = Depends(get_current_user)):
    db = get_supabase()
    result = db.table("api_keys").select("id, name, key_prefix, created_at, last_used_at").eq("user_id", current_user["id"]).order("created_at", desc=True).execute()
    data = result.data if hasattr(result, "data") else []
    return data

@router.post("")
async def create_api_key(payload: CreateApiKeyRequest, current_user: dict = Depends(get_current_user)):
    db = get_supabase()
    
    # Generate raw key
    raw_key = "vt_" + secrets.token_urlsafe(32)
    key_prefix = raw_key[:7] + "..."
    key_hash = hash_password(raw_key)
    
    result = db.table("api_keys").insert({
        "user_id": current_user["id"],
        "name": payload.name,
        "key_hash": key_hash,
        "key_prefix": key_prefix
    }).execute()
    
    data = result.data if hasattr(result, "data") else []
    if not data:
        raise HTTPException(status_code=500, detail="Failed to create API key")
        
    api_key_record = data[0]
    # Return raw key ONLY ONCE
    api_key_record["raw_key"] = raw_key
    return api_key_record

@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(key_id: str, current_user: dict = Depends(get_current_user)):
    db = get_supabase()
    db.table("api_keys").delete().eq("id", key_id).eq("user_id", current_user["id"]).execute()
    return None
