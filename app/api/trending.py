"""
app/api/trending.py — GET /api/trending
app/api/profile.py  — CRUD /api/profile
app/api/settings.py — CRUD /api/settings
"""
from fastapi import APIRouter, Depends, Query
from app.core.security import get_current_user
from app.core.supabase_client import get_supabase

# ── Trending ──────────────────────────────────────────────
router = APIRouter()

TRENDING_DATA = {
    "tech": [
        {"id": "tr_001", "title": "Claude 3.5 Sonnet vs GPT-4o — Which Is Actually Better?",        "viral_score": 96, "search_volume": "High",   "competition": "Medium", "keywords": ["Claude 3.5", "GPT-4o", "best AI 2024"]},
        {"id": "tr_002", "title": "I Built a Full App Using Only AI in 24 Hours",                    "viral_score": 94, "search_volume": "High",   "competition": "Low",    "keywords": ["vibe coding", "AI app builder", "cursor AI"]},
        {"id": "tr_003", "title": "Google Gemini 2.0 Features Nobody Is Talking About",              "viral_score": 91, "search_volume": "High",   "competition": "Low",    "keywords": ["Gemini 2.0", "Google AI 2024"]},
        {"id": "tr_004", "title": "The Free AI Image Generator Better Than Midjourney",              "viral_score": 89, "search_volume": "High",   "competition": "Medium", "keywords": ["free AI image", "FLUX AI", "Ideogram"]},
        {"id": "tr_005", "title": "How AI Is Replacing Software Engineers in 2025",                  "viral_score": 87, "search_volume": "Medium", "competition": "Low",    "keywords": ["AI replacing jobs", "future of coding"]},
        {"id": "tr_006", "title": "Sora Video AI — Is Hollywood Dead?",                              "viral_score": 85, "search_volume": "High",   "competition": "High",   "keywords": ["Sora AI", "OpenAI video", "AI video"]},
        {"id": "tr_007", "title": "5 AI Automation Tools That Run My Business on Autopilot",         "viral_score": 82, "search_volume": "Medium", "competition": "Low",    "keywords": ["AI automation", "n8n", "Make.com AI"]},
        {"id": "tr_008", "title": "The Dark Side of AI Nobody Talks About",                          "viral_score": 88, "search_volume": "Medium", "competition": "Low",    "keywords": ["AI dangers", "AI ethics", "AI risks 2024"]},
        {"id": "tr_009", "title": "I Used AI to Grow My YouTube Channel to 100K",                    "viral_score": 90, "search_volume": "High",   "competition": "Medium", "keywords": ["AI YouTube growth", "YouTube automation"]},
    ],
    "gaming": [
        {"id": "gm_001", "title": "GTA 6 vs Red Dead 3 — Which Should Rockstar Make First?", "viral_score": 95, "search_volume": "High", "competition": "High",   "keywords": ["GTA 6", "Red Dead 3", "Rockstar Games"]},
        {"id": "gm_002", "title": "I Played Every $1 Steam Game So You Don't Have To",       "viral_score": 91, "search_volume": "High", "competition": "Low",    "keywords": ["cheap Steam games", "Steam deals", "budget gaming"]},
        {"id": "gm_003", "title": "The BEST Gaming Setup Under $500 in 2024",                "viral_score": 88, "search_volume": "High", "competition": "Medium", "keywords": ["budget gaming setup", "gaming PC 2024"]},
    ],
    "finance": [
        {"id": "fn_001", "title": "How I Made $10K Passive Income With Zero Experience",      "viral_score": 93, "search_volume": "High", "competition": "High",   "keywords": ["passive income", "make money online 2024"]},
        {"id": "fn_002", "title": "The ETF That Beats the S&P 500 Every Year (Proven Data)", "viral_score": 89, "search_volume": "High", "competition": "Medium", "keywords": ["best ETF 2024", "S&P 500", "index funds"]},
    ],
}


@router.get("")
async def get_trending(
    niche: str = Query("tech"),
    sort: str = Query("viral_score"),
    current_user: dict = Depends(get_current_user),
):
    topics = TRENDING_DATA.get(niche, TRENDING_DATA["tech"])
    if sort == "competition":
        order = {"Low": 1, "Medium": 2, "High": 3}
        topics = sorted(topics, key=lambda t: order.get(t["competition"], 2))
    elif sort == "search_volume":
        order = {"High": 3, "Medium": 2, "Low": 1}
        topics = sorted(topics, key=lambda t: -order.get(t["search_volume"], 2))
    else:
        topics = sorted(topics, key=lambda t: -t["viral_score"])
    return {"niche": niche, "topics": topics}
