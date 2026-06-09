"""
app/services/rate_limit_service.py
Daily AI request rate limiting using usage_metrics table
"""
from datetime import date
from app.core.supabase_client import get_supabase
from app.core.config import settings


class RateLimitService:

    async def check(self, user_id: str) -> bool:
        """Return True if user is within daily limit."""
        db    = get_supabase()
        today = date.today().isoformat()
        try:
            row = db.table("usage_metrics").select("request_count").eq("user_id", user_id).eq("date", today).maybe_single().execute()
            row_data = row.data if row is not None else None
        except Exception:
            row_data = None
        count = row_data.get("request_count", 0) if row_data else 0
        return count < settings.AI_DAILY_REQUEST_LIMIT

    async def record(self, user_id: str, gen_type: str, tokens: int):
        """Increment request count and tokens for today."""
        db    = get_supabase()
        today = date.today().isoformat()
        try:
            row = db.table("usage_metrics").select("*").eq("user_id", user_id).eq("date", today).maybe_single().execute()
            row_data = row.data if row is not None else None
        except Exception:
            row_data = None

        if row_data:
            db.table("usage_metrics").update({
                "request_count": row_data["request_count"] + 1,
                "tokens_used":   row_data["tokens_used"] + tokens,
            }).eq("id", row_data["id"]).execute()
        else:
            db.table("usage_metrics").insert({
                "user_id":       user_id,
                "date":          today,
                "request_count": 1,
                "tokens_used":   tokens,
            }).execute()
