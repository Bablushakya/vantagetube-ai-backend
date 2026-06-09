"""
app/api/videos.py — Per-video analytics
GET /api/videos/{video_id}/analytics
GET /api/videos/{video_id}/seo-score
"""
from fastapi import APIRouter, Depends
from app.core.security import get_current_user
from app.services.analytics_service import AnalyticsService

router = APIRouter()
analytics_svc = AnalyticsService()


@router.get("/{video_id}/analytics")
async def get_video_analytics(video_id: str, current_user: dict = Depends(get_current_user)):
    return await analytics_svc.get_video_analytics(video_id, current_user["id"])


@router.get("/{video_id}/seo-score")
async def get_seo_score(video_id: str, current_user: dict = Depends(get_current_user)):
    return await analytics_svc.compute_seo_score(video_id, current_user["id"])
