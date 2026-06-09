"""
app/api/ai.py — AI generation endpoints (Gemini + Nano Banana)
POST /api/ai/generate-title
POST /api/ai/generate-description
POST /api/ai/generate-tags
POST /api/ai/generate-thumbnail
GET  /api/ai/history
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_user
from app.schemas.ai import (
    TitleRequest, TitlesResponse,
    DescriptionRequest, DescriptionResponse,
    TagsRequest, TagsResponse,
    ThumbnailRequest, ThumbnailResponse,
    GenerationHistoryResponse,
)
from app.services.ai_service import AIService
from app.services.rate_limit_service import RateLimitService

router  = APIRouter()
ai_svc  = AIService()
rl_svc  = RateLimitService()


async def check_quota(user: dict):
    allowed = await rl_svc.check(user["id"])
    if not allowed:
        raise HTTPException(status_code=429, detail="Daily AI request limit reached. Upgrade your plan for more.")


@router.post("/generate-title", response_model=TitlesResponse)
async def generate_title(payload: TitleRequest, current_user: dict = Depends(get_current_user)):
    await check_quota(current_user)
    result = await ai_svc.generate_titles(payload, current_user["id"])
    await rl_svc.record(current_user["id"], "title", result.tokens_used)
    return result


@router.post("/generate-description", response_model=DescriptionResponse)
async def generate_description(payload: DescriptionRequest, current_user: dict = Depends(get_current_user)):
    await check_quota(current_user)
    result = await ai_svc.generate_description(payload, current_user["id"])
    await rl_svc.record(current_user["id"], "description", result.tokens_used)
    return result


@router.post("/generate-tags", response_model=TagsResponse)
async def generate_tags(payload: TagsRequest, current_user: dict = Depends(get_current_user)):
    await check_quota(current_user)
    result = await ai_svc.generate_tags(payload, current_user["id"])
    await rl_svc.record(current_user["id"], "tags", result.tokens_used)
    return result


@router.post("/generate-thumbnail", response_model=ThumbnailResponse)
async def generate_thumbnail(payload: ThumbnailRequest, current_user: dict = Depends(get_current_user)):
    await check_quota(current_user)
    result = await ai_svc.generate_thumbnail(payload, current_user["id"])
    await rl_svc.record(current_user["id"], "thumbnail", result.tokens_used)
    return result


@router.get("/history", response_model=GenerationHistoryResponse)
async def get_history(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    search: str = None,
    tool_type: str = None,
    sort: str = "desc",
    current_user: dict = Depends(get_current_user),
):
    return await ai_svc.get_history(current_user["id"], page, limit, search, tool_type, sort)


@router.get("/history/{generation_id}")
async def get_generation(generation_id: str, current_user: dict = Depends(get_current_user)):
    gen = await ai_svc.get_generation(current_user["id"], generation_id)
    if not gen:
        raise HTTPException(status_code=404, detail="Generation not found")
    return gen


@router.delete("/history")
async def bulk_delete_history(payload: dict, current_user: dict = Depends(get_current_user)):
    ids = payload.get("ids", [])
    if not ids:
        return {"message": "No IDs provided"}
    await ai_svc.bulk_delete_generations(current_user["id"], ids)
    return {"message": f"Deleted {len(ids)} items"}


@router.delete("/history/{generation_id}", status_code=204)
async def delete_history(generation_id: str, current_user: dict = Depends(get_current_user)):
    await ai_svc.delete_generation(current_user["id"], generation_id)
    return None


@router.post("/history/{generation_id}/favorite")
async def toggle_favorite(generation_id: str, current_user: dict = Depends(get_current_user)):
    is_fav = await ai_svc.toggle_favorite(current_user["id"], generation_id)
    return {"favorite": is_fav}

