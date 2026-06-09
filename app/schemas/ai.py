"""
app/schemas/ai.py — AI generation request/response models
"""
from pydantic import BaseModel
from typing import Optional


class TitleRequest(BaseModel):
    keywords: str
    topic: str = ""
    audience: str = "General Audience"
    tone: str = "educational"  # educational | hype | provocative | formal


class TitleSuggestion(BaseModel):
    title: str
    score: int
    reason: str


class TitlesResponse(BaseModel):
    titles: list[TitleSuggestion]
    tokens_used: int


class DescriptionRequest(BaseModel):
    title: str
    keywords: str = ""
    include_timestamps: bool = True
    tone: str = "educational"


class DescriptionResponse(BaseModel):
    description: str
    word_count: int
    tokens_used: int


class TagsRequest(BaseModel):
    title: str
    description: str = ""
    keywords: str = ""


class TagsResponse(BaseModel):
    tags: list[str]
    tokens_used: int


class ThumbnailRequest(BaseModel):
    title: str
    description: str = ""
    style: str = "tech"  # tech | gaming | vlog | tutorial | finance | fitness


class ThumbnailResponse(BaseModel):
    prompt: str
    image_url: Optional[str] = None
    image_error: Optional[str] = None   # reason image generation failed, if any
    style: str
    tokens_used: int


class GenerationHistoryItem(BaseModel):
    id: str
    tool_type: str
    prompt: str
    output: str
    tokens_used: int
    model_name: str
    favorite: bool
    metadata: dict
    created_at: str
    updated_at: str

class BulkDeleteHistoryRequest(BaseModel):
    ids: list[str]


class GenerationHistoryResponse(BaseModel):
    items: list[GenerationHistoryItem]
    total: int
    page: int
