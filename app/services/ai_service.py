"""
app/services/ai_service.py
Gemini AI text generation + image generation service.

Image generation uses the new google-genai SDK (v2.6+) with response_modalities.
Models:
  - gemini-2.0-flash-preview-image-generation  (image gen, new SDK)
  - gemini-2.5-flash                            (text gen, old SDK)

All generation uses the same GEMINI_API_KEY — no separate API needed.
"""
import json
import re
import base64
import logging
from datetime import datetime, timezone

import google.generativeai as genai

# New google-genai SDK for image generation (supports response_modalities)
try:
    from google import genai as new_genai
    from google.genai import types as genai_types
    _NEW_GENAI_AVAILABLE = True
except ImportError:
    _NEW_GENAI_AVAILABLE = False

from app.core.config import settings
from app.core.supabase_client import get_supabase
from app.schemas.ai import (
    TitleRequest, TitlesResponse, TitleSuggestion,
    DescriptionRequest, DescriptionResponse,
    TagsRequest, TagsResponse,
    ThumbnailRequest, ThumbnailResponse,
    GenerationHistoryResponse, GenerationHistoryItem,
)

logger = logging.getLogger("vantagetube")

# Image generation model — gemini-2.5-flash-image confirmed working with new SDK
IMAGE_GEN_MODEL = "gemini-2.5-flash-image"


class AIService:
    def __init__(self):
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.model = genai.GenerativeModel(settings.GEMINI_MODEL)
            # New SDK client for image generation
            if _NEW_GENAI_AVAILABLE:
                self._image_client = new_genai.Client(api_key=settings.GEMINI_API_KEY)
            else:
                self._image_client = None
        else:
            self.model = None
            self._image_client = None

    def _save_generation(self, user_id: str, gen_type: str, prompt: str, content: str, tokens: int, model_name: str = "gemini-2.5-flash", metadata: dict = None):
        db = get_supabase()
        db.table("ai_generations").insert({
            "user_id":     user_id,
            "tool_type":   gen_type,
            "prompt":      prompt,
            "output":      content[:2000],
            "tokens_used": tokens,
            "model_name":  model_name,
            "metadata":    metadata or {},
            "created_at":  datetime.now(timezone.utc).isoformat(),
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }).execute()

    async def _gemini(self, prompt: str) -> tuple[str, int]:
        """Call Gemini and return (text, tokens_used)."""
        if not self.model:
            raise ValueError("GEMINI_API_KEY not configured")
        response = self.model.generate_content(prompt)
        text   = response.text
        tokens = response.usage_metadata.total_token_count if hasattr(response, "usage_metadata") else len(text) // 4
        return text, tokens

    # ── Titles ────────────────────────────────────────────
    async def generate_titles(self, req: TitleRequest, user_id: str) -> TitlesResponse:
        prompt = f"""You are a YouTube SEO expert. Generate exactly 5 viral YouTube title suggestions.

Video Topic: {req.topic or req.keywords}
Primary Keywords: {req.keywords}
Target Audience: {req.audience}
Tone/Style: {req.tone}

Return ONLY valid JSON in this exact format:
{{
  "titles": [
    {{"title": "...", "score": 85, "reason": "Brief explanation of why this title works"}},
    ...
  ]
}}

Rules:
- Each title under 70 characters
- Include power words, numbers, or curiosity gaps
- Score 70-99 based on CTR potential
- Vary the approach (list, question, bold claim, etc.)"""

        text, tokens = await self._gemini(prompt)
        # Extract JSON from response
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            raise ValueError("Gemini returned invalid JSON for titles")
        data = json.loads(match.group())
        titles = [TitleSuggestion(**t) for t in data.get("titles", [])]
        self._save_generation(user_id, "title", prompt, titles[0].title if titles else "", tokens)
        return TitlesResponse(titles=titles, tokens_used=tokens)

    # ── Description ───────────────────────────────────────
    async def generate_description(self, req: DescriptionRequest, user_id: str) -> DescriptionResponse:
        prompt = f"""You are a YouTube SEO copywriter. Write a complete, SEO-optimized YouTube description.

Video Title: {req.title}
Keywords: {req.keywords}
Tone: {req.tone}

Requirements:
- 150-250 words
- First 2 lines must be a strong hook (visible before "Show more")
- Include relevant emojis as bullet points
- Add a timestamps section with placeholder times
- End with a subscribe CTA
- Naturally include the keywords
- Do NOT include any JSON — just the description text."""

        text, tokens = await self._gemini(prompt)
        self._save_generation(user_id, "description", prompt, text[:500], tokens)
        word_count = len(text.split())
        return DescriptionResponse(description=text, word_count=word_count, tokens_used=tokens)

    # ── Tags ──────────────────────────────────────────────
    async def generate_tags(self, req: TagsRequest, user_id: str) -> TagsResponse:
        prompt = f"""You are a YouTube SEO expert. Generate exactly 15 optimized tags for this video.

Title: {req.title}
Description: {req.description[:300] if req.description else ''}
Keywords: {req.keywords}

Return ONLY valid JSON:
{{"tags": ["tag1", "tag2", ..., "tag15"]}}

Rules:
- Mix broad and specific tags
- Include the main keyword, variations, and related topics
- Each tag under 30 characters
- Include 2-3 multi-word phrases"""

        text, tokens = await self._gemini(prompt)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        data  = json.loads(match.group()) if match else {"tags": []}
        tags  = data.get("tags", [])[:15]
        self._save_generation(user_id, "tags", prompt, ", ".join(tags), tokens)
        return TagsResponse(tags=tags, tokens_used=tokens)

    # ── Thumbnail Prompt ──────────────────────────────────
    async def generate_thumbnail(self, req: ThumbnailRequest, user_id: str) -> ThumbnailResponse:
        style_guides = {
            "tech":     "Dark background, neon purple/cyan glows, tech UI elements, circuit patterns",
            "gaming":   "Vibrant colors, gaming controller, action poses, bold text overlays",
            "vlog":     "Bright natural lighting, personal/lifestyle setting, warm tones",
            "tutorial": "Clean white/light background, step indicators, professional look",
            "finance":  "Dark professional background, money/growth charts, gold accents",
            "fitness":  "High contrast, energetic pose, bold typography, sweat/action",
        }
        style_guide = style_guides.get(req.style, style_guides["tech"])

        prompt = f"""You are a YouTube thumbnail designer. Write a detailed image generation prompt.

Video Title: {req.title}
Style: {req.style} — {style_guide}

Create a detailed prompt for generating a 1280x720 YouTube thumbnail. Include:
- Specific background description
- Text overlay details (what text, font style, colors, size)
- Main subject/focal point
- Lighting and color grading
- Emotional impact and visual hierarchy

Return ONLY the image generation prompt as plain text, no JSON."""

        text, tokens = await self._gemini(prompt)
        prompt_text = text.strip()

        # Generate image using new google-genai SDK (gemini-2.5-flash-image)
        image_url, image_error = await self._generate_image_with_gemini(prompt_text)

        self._save_generation(user_id, "thumbnail", prompt, prompt_text[:500], tokens, model_name=IMAGE_GEN_MODEL, metadata={"style": req.style, "image_url": image_url, "image_error": image_error})
        return ThumbnailResponse(prompt=prompt_text, image_url=image_url, image_error=image_error, style=req.style, tokens_used=tokens)

    async def _generate_image_with_gemini(self, prompt: str) -> tuple[str | None, str | None]:
        """
        Generate image using new google-genai SDK (v2.6+) with response_modalities.
        Returns (base64_data_uri, error_message). On success error_message is None.
        On failure image_url is None and error_message describes why.
        """
        if not settings.GEMINI_API_KEY:
            msg = "GEMINI_API_KEY not configured"
            logger.warning(msg)
            return None, msg

        if not (self._image_client and _NEW_GENAI_AVAILABLE):
            msg = "Image generation SDK not available"
            logger.warning(msg)
            return None, msg

        try:
            response = self._image_client.models.generate_content(
                model=IMAGE_GEN_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"]
                ),
            )
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                    mime = part.inline_data.mime_type or "image/png"
                    b64 = base64.b64encode(part.inline_data.data).decode("utf-8")
                    logger.info(f"Thumbnail image generated successfully ({len(part.inline_data.data)} bytes)")
                    return f"data:{mime};base64,{b64}", None
            msg = "Image generation returned no image parts"
            logger.warning(msg)
            return None, msg

        except Exception as e:
            err_str = str(e)
            # Detect quota exhaustion (free tier limit)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                msg = "API quota exceeded for image generation. The text prompt above was generated successfully — you can use it with any image AI tool (Midjourney, DALL-E, etc.). To enable in-app image generation, upgrade your Gemini API plan at https://ai.google.dev/pricing"
                logger.warning(f"Image quota exhausted: {err_str[:200]}")
            elif "NOT_FOUND" in err_str or "404" in err_str:
                msg = f"Image model '{IMAGE_GEN_MODEL}' not available for your API key tier"
                logger.warning(f"Image model not found: {err_str[:200]}")
            else:
                msg = f"Image generation failed: {err_str[:120]}"
                logger.warning(f"Image generation error: {err_str[:200]}")
            return None, msg

    # ── History ───────────────────────────────────────────
    async def get_history(self, user_id: str, page: int = 1, limit: int = 10, search: str = None, tool_type: str = None, sort: str = "desc") -> GenerationHistoryResponse:
        db  = get_supabase()
        offset = (page - 1) * limit
        query = db.table("ai_generations").select("*", count="exact").eq("user_id", user_id)
        
        if tool_type:
            query = query.eq("tool_type", tool_type)
        if search:
            query = query.or_(f"prompt.ilike.%{search}%,output.ilike.%{search}%")
            
        order_desc = sort == "desc"
        result = query.order("created_at", desc=order_desc).range(offset, offset + limit - 1).execute()
        
        items = [GenerationHistoryItem(**r) for r in (result.data or [])]
        return GenerationHistoryResponse(items=items, total=result.count or 0, page=page)

    async def get_generation(self, user_id: str, generation_id: str) -> dict:
        db = get_supabase()
        res = db.table("ai_generations").select("*").eq("id", generation_id).eq("user_id", user_id).limit(1).execute()
        if not res.data:
            return None
        return res.data[0]

    async def delete_generation(self, user_id: str, generation_id: str):
        db = get_supabase()
        db.table("ai_generations").delete().eq("id", generation_id).eq("user_id", user_id).execute()

    async def bulk_delete_generations(self, user_id: str, generation_ids: list[str]):
        db = get_supabase()
        db.table("ai_generations").delete().in_("id", generation_ids).eq("user_id", user_id).execute()

    async def toggle_favorite(self, user_id: str, generation_id: str):
        db = get_supabase()
        gen = await self.get_generation(user_id, generation_id)
        if gen:
            db.table("ai_generations").update({"favorite": not gen["favorite"]}).eq("id", generation_id).execute()
            return not gen["favorite"]
        return False
