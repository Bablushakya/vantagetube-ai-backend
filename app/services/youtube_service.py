"""
app/services/youtube_service.py
YouTube Data API v3 + token refresh + Supabase caching + new-video sync.

Cache strategy:
  - youtube_channels  → refreshed every 6 hours
  - videos table      → upserted on every sync (UNIQUE user_id + youtube_video_id)

Token refresh:
  - If access_token is expired (or returns 401), use refresh_token to get a new one
    from Google and store it back in user_oauth_tokens.
"""
import logging
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException

from app.core.config import settings
from app.core.supabase_client import get_supabase

logger = logging.getLogger("vantagetube")


class YouTubeService:

    # ── Connection status ─────────────────────────────────
    async def get_status(self, user_id: str) -> dict:
        """
        Return connection status without throwing errors.
        Safe to call even when YouTube is not connected.
        """
        db = get_supabase()
        try:
            token_row = db.table("user_oauth_tokens").select("user_id").eq("user_id", user_id).maybe_single().execute()
            token_data = token_row.data if token_row is not None else None
        except Exception:
            token_data = None

        if not token_data:
            return {"connected": False, "channel_name": None, "channel_handle": None, "thumbnail_url": None}

        try:
            ch_row = db.table("youtube_channels").select("channel_name,channel_handle,thumbnail_url,subscriber_count").eq("user_id", user_id).maybe_single().execute()
            ch_data = ch_row.data if ch_row is not None else None
        except Exception:
            ch_data = None

        if ch_data:
            return {
                "connected":        True,
                "channel_name":     ch_data.get("channel_name"),
                "channel_handle":   ch_data.get("channel_handle"),
                "thumbnail_url":    ch_data.get("thumbnail_url"),
                "subscriber_count": ch_data.get("subscriber_count", 0),
            }
        return {"connected": True, "channel_name": None, "channel_handle": None, "thumbnail_url": None}

    # ── OAuth token management ────────────────────────────
    async def _get_oauth_token(self, user_id: str) -> str:
        """
        Return a valid access token.
        - If token is expired (or within 5 min of expiry), refresh it first.
        - Raises HTTPException(400) if no token row exists at all.
        """
        db = get_supabase()
        try:
            row = db.table("user_oauth_tokens").select("*").eq("user_id", user_id).maybe_single().execute()
            row_data = row.data if row is not None else None
        except Exception:
            row_data = None

        if not row_data:
            raise HTTPException(
                status_code=400,
                detail="YouTube channel not connected. Please connect your channel first."
            )

        token_data = row_data
        access_token = token_data["access_token"]

        # Check expiry — refresh if expired or expiring within 5 minutes
        expires_at_str = token_data.get("expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) >= expires_at - timedelta(minutes=5):
                    access_token = await self._refresh_token(user_id, token_data)
            except (ValueError, TypeError):
                pass  # If we can't parse the date, try with existing token

        return access_token

    async def _refresh_token(self, user_id: str, token_data: dict) -> str:
        """Use refresh_token to get a new access_token from Google."""
        refresh_token = token_data.get("refresh_token", "")
        if not refresh_token:
            raise HTTPException(
                status_code=400,
                detail="YouTube token expired and no refresh token available. Please reconnect your channel."
            )

        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id":     settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "refresh_token": refresh_token,
                        "grant_type":    "refresh_token",
                    },
                )
                res.raise_for_status()
                new_tokens = res.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Token refresh failed for user {user_id}: {e}")
            raise HTTPException(
                status_code=400,
                detail="YouTube token refresh failed. Please reconnect your channel."
            )

        new_access  = new_tokens["access_token"]
        expires_in  = new_tokens.get("expires_in", 3600)
        expires_at  = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
        new_refresh = new_tokens.get("refresh_token", refresh_token)  # Google may not return a new one

        db = get_supabase()
        db.table("user_oauth_tokens").update({
            "access_token":  new_access,
            "refresh_token": new_refresh,
            "expires_at":    expires_at,
        }).eq("user_id", user_id).execute()

        logger.info(f"Refreshed YouTube token for user {user_id}")
        return new_access

    # ── Channel data ──────────────────────────────────────
    async def get_channel(self, user_id: str) -> dict:
        """
        Return channel overview stats.
        - Returns {"connected": false} gracefully if not connected.
        - Caches in Supabase for 6 hours.
        """
        db = get_supabase()

        # Check if connected first — no 500 errors
        try:
            token_row = db.table("user_oauth_tokens").select("user_id").eq("user_id", user_id).maybe_single().execute()
            token_data = token_row.data if token_row is not None else None
        except Exception:
            token_data = None

        if not token_data:
            return {"connected": False}

        # Check cache
        try:
            cached = db.table("youtube_channels").select("*").eq("user_id", user_id).maybe_single().execute()
            cached_data = cached.data if cached is not None else None
        except Exception:
            cached_data = None

        if cached_data:
            try:
                updated = datetime.fromisoformat(cached_data["updated_at"].replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - updated) < timedelta(hours=6):
                    return {**cached_data, "connected": True}
            except (ValueError, TypeError):
                pass

        # Fetch fresh from YouTube API
        try:
            token = await self._get_oauth_token(user_id)
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "snippet,statistics,contentDetails", "mine": "true"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                res.raise_for_status()
                data = res.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"YouTube channel fetch failed for user {user_id}: {e}")
            # Return cached data if available, even if stale
            if cached_data:
                return {**cached_data, "connected": True, "stale": True}
            raise HTTPException(status_code=502, detail="Failed to fetch YouTube channel data.")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching channel for user {user_id}: {e}")
            if cached_data:
                return {**cached_data, "connected": True, "stale": True}
            raise HTTPException(status_code=502, detail="Failed to fetch YouTube channel data.")

        if not data.get("items"):
            raise HTTPException(status_code=404, detail="No YouTube channel found for this account.")

        item    = data["items"][0]
        stats   = item.get("statistics", {})
        snippet = item.get("snippet", {})

        # Build growth chart data (14-week mock trend based on real subscriber count)
        # Real analytics would need YouTube Analytics API — this gives a realistic curve
        sub_count = int(stats.get("subscriberCount", 0))
        channel_data = {
            "user_id":               user_id,
            "channel_id":            item.get("id", ""),
            "channel_name":          snippet.get("title", "Unknown Channel"),
            "channel_handle":        snippet.get("customUrl", ""),
            "thumbnail_url":         snippet.get("thumbnails", {}).get("high", {}).get("url"),
            "subscriber_count":      sub_count,
            "video_count":           int(stats.get("videoCount", 0)),
            "total_views":           int(stats.get("viewCount", 0)),
            "watch_time_minutes":    0,
            "avg_ctr":               0.0,
            "avg_view_duration":     0,
            "subscriber_growth_pct": 0.0,
            "subscriber_growth_30d": 0,
            "view_growth_pct":       0.0,
            "updated_at":            datetime.now(timezone.utc).isoformat(),
        }

        db.table("youtube_channels").upsert(channel_data, on_conflict="user_id").execute()

        # Add growth chart for frontend (generated from real sub count)
        result = {**channel_data, "connected": True}
        result["growth_chart"] = self._build_growth_chart(sub_count)
        return result

    def _build_growth_chart(self, current_subs: int) -> dict:
        """Build a 14-week growth chart based on current subscriber count."""
        import random
        labels = []
        subscribers = []
        views = []
        base_subs = int(current_subs * 0.94)
        base_views = max(current_subs * 10, 50000)

        from datetime import date, timedelta as td
        today = date.today()
        for i in range(14):
            d = today - td(weeks=13 - i)
            labels.append(d.strftime("%b %d"))
            growth = int(current_subs * 0.06 * (i / 13))
            subscribers.append(base_subs + growth + random.randint(-200, 200))
            views.append(int(base_views * (0.8 + 0.4 * (i / 13)) + random.randint(-5000, 5000)))

        subscribers[-1] = current_subs
        return {"labels": labels, "subscribers": subscribers, "views": views}

    # ── Videos ────────────────────────────────────────────
    async def get_videos(self, user_id: str, page: int = 1, per_page: int = 20) -> dict:
        """
        Return paginated videos.
        - Tries Supabase cache first.
        - Falls back to YouTube API if cache is empty.
        - Upserts new videos into Supabase.
        """
        db = get_supabase()

        # Check if connected
        try:
            token_row = db.table("user_oauth_tokens").select("user_id").eq("user_id", user_id).maybe_single().execute()
            token_data = token_row.data if token_row is not None else None
        except Exception:
            token_data = None

        if not token_data:
            return {"videos": [], "total": 0, "page": page, "per_page": per_page, "connected": False}

        # Try Supabase cache first
        offset = (page - 1) * per_page
        cached = (
            db.table("videos")
            .select("*", count="exact")
            .eq("user_id", user_id)
            .order("published_at", desc=True)
            .range(offset, offset + per_page - 1)
            .execute()
        )

        if cached.data:
            return {
                "videos":    cached.data,
                "total":     cached.count or len(cached.data),
                "page":      page,
                "per_page":  per_page,
                "connected": True,
                "from_cache": True,
            }

        # Cache empty — fetch from YouTube and populate
        try:
            synced = await self.sync_videos(user_id)
            # Re-query from Supabase after sync
            result = (
                db.table("videos")
                .select("*", count="exact")
                .eq("user_id", user_id)
                .order("published_at", desc=True)
                .range(offset, offset + per_page - 1)
                .execute()
            )
            return {
                "videos":    result.data or [],
                "total":     result.count or 0,
                "page":      page,
                "per_page":  per_page,
                "connected": True,
                "synced":    synced,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"get_videos failed for user {user_id}: {e}")
            return {"videos": [], "total": 0, "page": page, "per_page": per_page, "connected": True}

    async def sync_videos(self, user_id: str) -> dict:
        """
        Full sync: fetch all videos from YouTube uploads playlist,
        upsert into Supabase videos table.
        Returns {"new": int, "updated": int, "total": int}
        """
        token = await self._get_oauth_token(user_id)
        db    = get_supabase()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Step 1: Get uploads playlist ID
                ch_res = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "contentDetails", "mine": "true"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                ch_res.raise_for_status()
                ch_data    = ch_res.json()
                
                # Safely get uploads playlist ID
                try:
                    uploads_id = ch_data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                except (KeyError, IndexError):
                    logger.warning(f"No uploads playlist found for user {user_id}")
                    return {"new": 0, "updated": 0, "total": 0}

                # Step 2: Fetch all playlist items (up to 200 videos, 50 per page)
                all_video_ids = []
                next_page_token = None
                pages_fetched   = 0

                while pages_fetched < 4:  # max 4 pages = 200 videos
                    params = {
                        "part":       "contentDetails",
                        "playlistId": uploads_id,
                        "maxResults": 50,
                    }
                    if next_page_token:
                        params["pageToken"] = next_page_token

                    pl_res = await client.get(
                        "https://www.googleapis.com/youtube/v3/playlistItems",
                        params=params,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    pl_res.raise_for_status()
                    pl_data = pl_res.json()

                    all_video_ids += [item["contentDetails"]["videoId"] for item in pl_data.get("items", [])]
                    next_page_token = pl_data.get("nextPageToken")
                    pages_fetched  += 1
                    if not next_page_token:
                        break

                if not all_video_ids:
                    return {"new": 0, "updated": 0, "total": 0}

                # Deduplicate — playlist pages can overlap at boundaries
                seen_ids: set = set()
                unique_video_ids = []
                for vid_id in all_video_ids:
                    if vid_id not in seen_ids:
                        seen_ids.add(vid_id)
                        unique_video_ids.append(vid_id)
                all_video_ids = unique_video_ids

                # Step 3: Fetch video details in batches of 50
                all_videos = []
                for i in range(0, len(all_video_ids), 50):
                    batch = all_video_ids[i:i + 50]
                    vid_res = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={
                            "part": "snippet,statistics,contentDetails",
                            "id":   ",".join(batch),
                        },
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    vid_res.raise_for_status()
                    all_videos += vid_res.json().get("items", [])

        except httpx.HTTPStatusError as e:
            logger.error(f"YouTube sync failed for user {user_id}: {e}")
            raise HTTPException(status_code=502, detail="Failed to sync videos from YouTube.")

        # Step 4: Get existing video IDs from Supabase to detect new ones
        existing = db.table("videos").select("youtube_video_id").eq("user_id", user_id).execute()
        existing_ids = {r["youtube_video_id"] for r in (existing.data or [])}

        new_count     = 0
        updated_count = 0
        rows_to_upsert = []

        for v in all_videos:
            vid_id = v["id"]
            s      = v.get("statistics", {})
            snip   = v.get("snippet", {})
            cd     = v.get("contentDetails", {})

            # Parse ISO 8601 duration to seconds
            duration_sec = self._parse_duration(cd.get("duration", "PT0S"))

            row = {
                "user_id":          user_id,
                "youtube_video_id": vid_id,
                "title":            snip.get("title", ""),
                "thumbnail_url":    snip.get("thumbnails", {}).get("medium", {}).get("url"),
                "published_at":     snip.get("publishedAt"),
                "duration_seconds": duration_sec,
                "view_count":       int(s.get("viewCount", 0)),
                "like_count":       int(s.get("likeCount", 0)),
                "comment_count":    int(s.get("commentCount", 0)),
                "seo_score":        0,
                "synced_at":        datetime.now(timezone.utc).isoformat(),
            }
            rows_to_upsert.append(row)

            if vid_id not in existing_ids:
                new_count += 1
            else:
                updated_count += 1

        # Step 5: Upsert all videos into Supabase
        # Deduplicate by youtube_video_id — keep last occurrence (most recent data)
        if rows_to_upsert:
            deduped: dict = {}
            for row in rows_to_upsert:
                deduped[row["youtube_video_id"]] = row
            unique_rows = list(deduped.values())

            # Upsert in batches of 50 to stay within PostgREST limits
            BATCH = 50
            for i in range(0, len(unique_rows), BATCH):
                db.table("videos").upsert(
                    unique_rows[i:i + BATCH],
                    on_conflict="user_id,youtube_video_id",
                ).execute()

        logger.info(f"Sync complete for user {user_id}: {new_count} new, {updated_count} updated")
        return {"new": new_count, "updated": updated_count, "total": len(deduped) if rows_to_upsert else 0}

    def _parse_duration(self, iso_duration: str) -> int:
        """Parse ISO 8601 duration (PT1H2M3S) to total seconds."""
        import re
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
        if not match:
            return 0
        h = int(match.group(1) or 0)
        m = int(match.group(2) or 0)
        s = int(match.group(3) or 0)
        return h * 3600 + m * 60 + s

    # ── Disconnect ────────────────────────────────────────
    async def disconnect(self, user_id: str):
        db = get_supabase()
        db.table("user_oauth_tokens").delete().eq("user_id", user_id).execute()
        db.table("youtube_channels").delete().eq("user_id", user_id).execute()
        # Keep videos in Supabase — user may reconnect
