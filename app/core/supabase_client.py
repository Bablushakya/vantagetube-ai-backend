"""
app/core/supabase_client.py
Initialises the Supabase client using the current supabase-py v2 API.
Uses create_client() with service role key for server-side operations.
"""
from supabase import create_client, Client
from app.core.config import settings

_client: Client | None = None


def get_supabase() -> Client:
    """Return singleton Supabase client (service role — bypasses RLS)."""
    global _client
    if _client is None:
        _client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_ROLE_KEY,
        )
    return _client


def init_supabase() -> Client:
    """Call once at application startup via lifespan."""
    return get_supabase()
