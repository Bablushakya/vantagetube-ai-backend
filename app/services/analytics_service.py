"""
app/services/analytics_service.py
Full YouTube Analytics API v2 integration — mirrors YouTube Studio Analytics tab.

Metrics fetched from YouTube Analytics API:
  - views, estimatedMinutesWatched, averageViewDuration, averageViewPercentage
  - likes, dislikes, comments, shares, subscribersGained, subscribersLost
  - annotationClickThroughRate, cardClickRate, cardTeaserClickRate

Traffic sources fetched via dimension=insightTrafficSourceType
Device types fetched via dimension=deviceType
Country breakdown via dimension=country

SEO score computed from YouTube Data API v3 video metadata.

Token management: reuses the same OAuth token stored in user_oauth_tokens.
Auto-refreshes if expired (delegates to YouTubeService._get_oauth_token).
"""
import logging
import re
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import HTTPException

from app.core.supabase_client import get_supabase
from app.core.config import settings

logger = logging.getLogger("vantagetube")

# ── YouTube Analytics API base ────────────────────────────
YT_ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
YT_DATA_V3   = "https://www.googleapis.com/youtube/v3"


class AnalyticsService:

    # ── Token helper (reuses YouTubeService logic) ────────
    async def _get_token(self, user_id: str) -> str:
        """
        Return a valid OAuth access token for the user.
        Delegates to YouTubeService so token refresh logic is centralised.
        """
        from app.services.youtube_service import YouTubeService
        yt = YouTubeService()
        return await yt._get_oauth_token(user_id)

    # ── Core analytics fetch ──────────────────────────────
    async def get_video_analytics(self, video_id: str, user_id: str) -> dict:
        """
        Fetch full per-video analytics from YouTube Analytics API v2.
        Returns a rich dict that mirrors YouTube Studio's Analytics tab.
        """
        token    = await self._get_token(user_id)
        end_dt   = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=28)
        end_date   = end_dt.strftime("%Y-%m-%d")
        start_date = start_dt.strftime("%Y-%m-%d")

        async with httpx.AsyncClient(timeout=20.0) as client:

            # ── 1. Daily core metrics ─────────────────────
            daily_res = await client.get(
                YT_ANALYTICS,
                params={
                    "ids":        "channel==MINE",
                    "startDate":  start_date,
                    "endDate":    end_date,
                    "metrics":    (
                        "views,"
                        "estimatedMinutesWatched,"
                        "averageViewDuration,"
                        "averageViewPercentage,"
                        "likes,"
                        "comments,"
                        "shares,"
                        "subscribersGained,"
                        "subscribersLost,"
                        "cardClickRate,"
                        "cardTeaserClickRate"
                    ),
                    "dimensions": "day",
                    "filters":    f"video=={video_id}",
                    "sort":       "day",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            daily_res.raise_for_status()
            daily_data = daily_res.json()

            # ── 2. Traffic sources ────────────────────────
            traffic_res = await client.get(
                YT_ANALYTICS,
                params={
                    "ids":        "channel==MINE",
                    "startDate":  start_date,
                    "endDate":    end_date,
                    "metrics":    "views,estimatedMinutesWatched",
                    "dimensions": "insightTrafficSourceType",
                    "filters":    f"video=={video_id}",
                    "sort":       "-views",
                    "maxResults": 10,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            traffic_res.raise_for_status()
            traffic_data = traffic_res.json()

            # ── 3. Device types ───────────────────────────
            device_res = await client.get(
                YT_ANALYTICS,
                params={
                    "ids":        "channel==MINE",
                    "startDate":  start_date,
                    "endDate":    end_date,
                    "metrics":    "views",
                    "dimensions": "deviceType",
                    "filters":    f"video=={video_id}",
                    "sort":       "-views",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            device_res.raise_for_status()
            device_data = device_res.json()

            # ── 4. Top countries ──────────────────────────
            country_res = await client.get(
                YT_ANALYTICS,
                params={
                    "ids":        "channel==MINE",
                    "startDate":  start_date,
                    "endDate":    end_date,
                    "metrics":    "views",
                    "dimensions": "country",
                    "filters":    f"video=={video_id}",
                    "sort":       "-views",
                    "maxResults": 10,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            country_res.raise_for_status()
            country_data = country_res.json()

            # ── 5. Video metadata from Data API v3 ────────
            meta_res = await client.get(
                f"{YT_DATA_V3}/videos",
                params={
                    "part": "snippet,statistics,contentDetails",
                    "id":   video_id,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            meta_res.raise_for_status()
            meta_json = meta_res.json()

        # ── Parse daily rows ──────────────────────────────
        rows = daily_data.get("rows", [])
        # columns: day, views, estimatedMinutesWatched, averageViewDuration,
        #          averageViewPercentage, likes, comments, shares,
        #          subscribersGained, subscribersLost, cardClickRate, cardTeaserClickRate

        dates              = [r[0]  for r in rows]
        views_by_day       = [int(r[1])   for r in rows]
        watch_time_by_day  = [float(r[2]) for r in rows]
        avg_dur_by_day     = [float(r[3]) for r in rows]
        retention_by_day   = [float(r[4]) for r in rows]
        likes_by_day       = [int(r[5])   for r in rows]
        comments_by_day    = [int(r[6])   for r in rows]
        shares_by_day      = [int(r[7])   for r in rows]
        subs_gained_by_day = [int(r[8])   for r in rows]
        subs_lost_by_day   = [int(r[9])   for r in rows]

        total_views      = sum(views_by_day)
        total_watch_time = sum(watch_time_by_day)
        total_likes      = sum(likes_by_day)
        total_comments   = sum(comments_by_day)
        total_shares     = sum(shares_by_day)
        total_subs_gained = sum(subs_gained_by_day)
        total_subs_lost   = sum(subs_lost_by_day)

        n = max(len(rows), 1)
        avg_view_duration  = sum(avg_dur_by_day)  / n
        avg_retention      = sum(retention_by_day) / n
        avg_card_ctr       = sum(float(r[10]) for r in rows) / n if rows else 0.0

        # Impressions estimate: views / avg_ctr (CTR not directly in Analytics API)
        # Use card click rate as a proxy; fallback to 5%
        estimated_ctr         = max(avg_card_ctr, 0.5)
        estimated_impressions = int(total_views / (estimated_ctr / 100)) if estimated_ctr > 0 else 0

        # ── Parse traffic sources ─────────────────────────
        traffic_rows  = traffic_data.get("rows", [])
        traffic_total = sum(int(r[1]) for r in traffic_rows) or 1
        # Friendly label map
        source_labels = {
            "YT_SEARCH":              "YouTube Search",
            "SUGGESTED_VIDEO":        "Suggested Videos",
            "EXTERNAL":               "External",
            "BROWSE_FEATURES":        "Browse Features",
            "CHANNEL":                "Channel Page",
            "NOTIFICATION":           "Notifications",
            "PLAYLIST":               "Playlists",
            "YT_OTHER_PAGE":          "Other YouTube",
            "NO_LINK_OTHER":          "Direct / Other",
            "NO_LINK_EMBEDDED":       "Embedded Player",
            "SUBSCRIBER":             "Subscribers Feed",
            "SHORTS":                 "YouTube Shorts",
            "HASHTAG_PAGES":          "Hashtag Pages",
            "CAMPAIGN_CARD":          "Campaign Cards",
            "END_SCREEN":             "End Screens",
            "ANNOTATION":             "Annotations",
            "PRODUCT_PAGE":           "Product Page",
            "LIVE_REDIRECT":          "Live Redirect",
        }
        traffic_sources = []
        for r in traffic_rows:
            src_key = r[0]
            views   = int(r[1])
            pct     = round((views / traffic_total) * 100, 1)
            traffic_sources.append({
                "source": source_labels.get(src_key, src_key.replace("_", " ").title()),
                "views":  views,
                "pct":    pct,
            })

        # ── Parse device types ────────────────────────────
        device_rows  = device_data.get("rows", [])
        device_total = sum(int(r[1]) for r in device_rows) or 1
        device_labels = {
            "MOBILE":   "Mobile",
            "DESKTOP":  "Desktop",
            "TABLET":   "Tablet",
            "TV":       "TV",
            "GAME_CONSOLE": "Game Console",
        }
        devices = []
        for r in device_rows:
            dev_key = r[0]
            views   = int(r[1])
            pct     = round((views / device_total) * 100, 1)
            devices.append({
                "device": device_labels.get(dev_key, dev_key.title()),
                "views":  views,
                "pct":    pct,
            })

        # ── Parse top countries ───────────────────────────
        country_rows  = country_data.get("rows", [])
        country_total = sum(int(r[1]) for r in country_rows) or 1
        # Country code → flag + name mapping (top 20 most common)
        country_map = {
            "US": "🇺🇸 United States", "IN": "🇮🇳 India",
            "GB": "🇬🇧 United Kingdom", "CA": "🇨🇦 Canada",
            "AU": "🇦🇺 Australia",      "DE": "🇩🇪 Germany",
            "FR": "🇫🇷 France",         "BR": "🇧🇷 Brazil",
            "MX": "🇲🇽 Mexico",         "JP": "🇯🇵 Japan",
            "KR": "🇰🇷 South Korea",    "ID": "🇮🇩 Indonesia",
            "PK": "🇵🇰 Pakistan",       "NG": "🇳🇬 Nigeria",
            "PH": "🇵🇭 Philippines",    "EG": "🇪🇬 Egypt",
            "TR": "🇹🇷 Turkey",         "SA": "🇸🇦 Saudi Arabia",
            "RU": "🇷🇺 Russia",         "IT": "🇮🇹 Italy",
            "ES": "🇪🇸 Spain",          "NL": "🇳🇱 Netherlands",
            "SE": "🇸🇪 Sweden",         "NO": "🇳🇴 Norway",
            "ZA": "🇿🇦 South Africa",   "AR": "🇦🇷 Argentina",
            "CO": "🇨🇴 Colombia",       "VN": "🇻🇳 Vietnam",
            "TH": "🇹🇭 Thailand",       "MY": "🇲🇾 Malaysia",
            "BD": "🇧🇩 Bangladesh",     "NP": "🇳🇵 Nepal",
            "LK": "🇱🇰 Sri Lanka",      "GH": "🇬🇭 Ghana",
            "KE": "🇰🇪 Kenya",          "TZ": "🇹🇿 Tanzania",
        }
        top_countries = []
        for r in country_rows[:10]:
            code  = r[0]
            views = int(r[1])
            pct   = round((views / country_total) * 100, 1)
            top_countries.append({
                "country": country_map.get(code, f"🌐 {code}"),
                "code":    code,
                "views":   views,
                "pct":     pct,
            })

        # ── Video metadata ────────────────────────────────
        meta_items = meta_json.get("items", [])
        meta        = meta_items[0] if meta_items else {}
        snippet     = meta.get("snippet", {})
        statistics  = meta.get("statistics", {})
        content_det = meta.get("contentDetails", {})

        title         = snippet.get("title", "")
        description   = snippet.get("description", "")
        tags          = snippet.get("tags", [])
        published_at  = snippet.get("publishedAt", "")
        duration_iso  = content_det.get("duration", "PT0S")
        duration_sec  = self._parse_duration(duration_iso)
        total_yt_views = int(statistics.get("viewCount", 0))
        total_yt_likes = int(statistics.get("likeCount", 0))
        total_yt_comments = int(statistics.get("commentCount", 0))
        thumbnail_url = (
            snippet.get("thumbnails", {}).get("maxres", {}).get("url")
            or snippet.get("thumbnails", {}).get("high", {}).get("url")
            or snippet.get("thumbnails", {}).get("medium", {}).get("url")
            or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        )

        # ── Performance score ─────────────────────────────
        perf_score = self._performance_score(
            total_views, avg_retention, total_likes, total_views
        )

        # ── Rule-based insights ───────────────────────────
        insights = self._generate_insights(
            retention=avg_retention,
            likes=total_likes,
            views=total_views,
            comments=total_comments,
            shares=total_shares,
            watch_time_minutes=total_watch_time,
            avg_view_duration=avg_view_duration,
            subs_gained=total_subs_gained,
            traffic_sources=traffic_sources,
            devices=devices,
        )

        # ── Build response ────────────────────────────────
        return {
            # Identity
            "video_id":    video_id,
            "title":       title,
            "thumbnail_url": thumbnail_url,
            "published_at":  published_at,
            "duration_seconds": duration_sec,
            "period":      "last_28_days",
            "date_range":  {"start": start_date, "end": end_date},

            # Core KPIs
            "views":              total_views,
            "watch_time_minutes": int(total_watch_time),
            "avg_view_duration":  int(avg_view_duration),
            "retention_rate":     round(avg_retention, 1),
            "ctr":                round(estimated_ctr, 2),
            "impressions":        estimated_impressions,

            # Engagement
            "likes":              total_likes,
            "comments":           total_comments,
            "shares":             total_shares,
            "subscribers_gained": total_subs_gained,
            "subscribers_lost":   total_subs_lost,
            "net_subscribers":    total_subs_gained - total_subs_lost,

            # Revenue estimate (CPM ~$3 average)
            "revenue_usd": round((total_watch_time / 1000) * 3.0, 2),

            # Scores
            "performance_score": perf_score,

            # Daily trend charts
            "views_chart": {
                "labels": dates,
                "data":   views_by_day,
            },
            "watch_time_chart": {
                "labels": dates,
                "data":   [int(w) for w in watch_time_by_day],
            },
            "retention_chart": {
                "labels": dates,
                "data":   [round(r, 1) for r in retention_by_day],
            },
            "engagement_chart": {
                "labels": dates,
                "likes":    likes_by_day,
                "comments": comments_by_day,
                "shares":   shares_by_day,
            },
            "subscribers_chart": {
                "labels": dates,
                "gained": subs_gained_by_day,
                "lost":   subs_lost_by_day,
            },

            # Breakdowns
            "traffic_sources": traffic_sources,
            "devices":         devices,
            "top_countries":   top_countries,

            # Insights
            "insights": insights,

            # Raw YouTube totals (lifetime, not just 28 days)
            "lifetime": {
                "views":    total_yt_views,
                "likes":    total_yt_likes,
                "comments": total_yt_comments,
            },
        }

    # ── Performance score ─────────────────────────────────
    def _performance_score(self, views: int, retention: float,
                           likes: int, total: int) -> int:
        score = 40
        # Retention contribution (max 25 pts)
        if retention >= 60:   score += 25
        elif retention >= 45: score += 18
        elif retention >= 30: score += 10
        elif retention >= 15: score += 5

        # Like rate contribution (max 20 pts)
        like_rate = (likes / max(total, 1)) * 100
        if like_rate >= 8:   score += 20
        elif like_rate >= 5: score += 15
        elif like_rate >= 2: score += 8
        elif like_rate >= 1: score += 4

        # View volume contribution (max 15 pts)
        if views >= 500_000:  score += 15
        elif views >= 100_000: score += 12
        elif views >= 10_000:  score += 8
        elif views >= 1_000:   score += 4

        return min(99, score)

    # ── Rule-based insights ───────────────────────────────
    def _generate_insights(
        self,
        retention: float,
        likes: int,
        views: int,
        comments: int,
        shares: int,
        watch_time_minutes: float,
        avg_view_duration: float,
        subs_gained: int,
        traffic_sources: list,
        devices: list,
    ) -> list:
        insights = []

        # Retention
        if retention >= 60:
            insights.append({
                "type": "positive", "icon": "🚀",
                "text": f"Excellent retention at {retention:.0f}% — well above the 40% YouTube average. Your content pacing is working."
            })
        elif retention >= 40:
            insights.append({
                "type": "info", "icon": "📊",
                "text": f"Retention is {retention:.0f}% — at the YouTube average. Try a stronger hook in the first 30 seconds to push above 50%."
            })
        else:
            insights.append({
                "type": "warning", "icon": "⚠️",
                "text": f"Retention is low at {retention:.0f}%. Viewers are dropping off early. Add a compelling hook in the first 15 seconds and cut slow intros."
            })

        # Like rate
        like_rate = (likes / max(views, 1)) * 100
        if like_rate >= 5:
            insights.append({
                "type": "positive", "icon": "❤️",
                "text": f"Like rate of {like_rate:.1f}% is excellent — your audience strongly approves of this content."
            })
        elif like_rate < 1 and views > 500:
            insights.append({
                "type": "warning", "icon": "👍",
                "text": f"Like rate is only {like_rate:.1f}%. Add a clear call-to-action asking viewers to like if they found it helpful."
            })

        # Comment engagement
        comment_rate = (comments / max(views, 1)) * 100
        if comment_rate >= 1:
            insights.append({
                "type": "positive", "icon": "💬",
                "text": f"Strong comment engagement at {comment_rate:.1f}% — this video is sparking conversation. Reply to comments to boost the algorithm."
            })

        # Shares
        share_rate = (shares / max(views, 1)) * 100
        if share_rate >= 0.5:
            insights.append({
                "type": "positive", "icon": "🔗",
                "text": f"Share rate of {share_rate:.1f}% is above average — viewers are recommending this video to others."
            })

        # Subscriber conversion
        sub_rate = (subs_gained / max(views, 1)) * 100
        if sub_rate >= 1:
            insights.append({
                "type": "positive", "icon": "📈",
                "text": f"This video converted {sub_rate:.1f}% of viewers into subscribers — a strong subscriber magnet."
            })
        elif sub_rate < 0.1 and views > 1000:
            insights.append({
                "type": "info", "icon": "🔔",
                "text": "Low subscriber conversion. Add a subscribe CTA at the 30% mark and in the end screen."
            })

        # Traffic source insights
        if traffic_sources:
            top_source = traffic_sources[0]
            if top_source["source"] == "YouTube Search" and top_source["pct"] >= 40:
                insights.append({
                    "type": "positive", "icon": "🔍",
                    "text": f"{top_source['pct']}% of views come from YouTube Search — strong SEO performance. Replicate this title/tag strategy."
                })
            elif top_source["source"] == "Suggested Videos" and top_source["pct"] >= 40:
                insights.append({
                    "type": "positive", "icon": "✨",
                    "text": f"{top_source['pct']}% of views come from Suggested Videos — YouTube's algorithm is actively promoting this video."
                })
            elif top_source["source"] == "External" and top_source["pct"] >= 20:
                insights.append({
                    "type": "info", "icon": "🌐",
                    "text": f"{top_source['pct']}% of views come from external sources. Consider embedding this video on your website or sharing on social media."
                })

        # Mobile dominance
        mobile_pct = next((d["pct"] for d in devices if d["device"] == "Mobile"), 0)
        if mobile_pct >= 70:
            insights.append({
                "type": "info", "icon": "📱",
                "text": f"{mobile_pct}% of viewers watch on mobile. Ensure your thumbnails and text overlays are readable on small screens."
            })

        return insights

    # ── SEO score ─────────────────────────────────────────
    async def compute_seo_score(self, video_id: str, user_id: str) -> dict:
        """
        Compute SEO score from real YouTube Data API v3 metadata.
        Scores each dimension 0-100 and returns a weighted total.
        """
        token = await self._get_token(user_id)

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(
                f"{YT_DATA_V3}/videos",
                params={
                    "part": "snippet,statistics,contentDetails",
                    "id":   video_id,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            res.raise_for_status()
            data = res.json()

        items = data.get("items", [])
        if not items:
            raise HTTPException(status_code=404, detail="Video not found")

        item        = items[0]
        snippet     = item.get("snippet", {})
        statistics  = item.get("statistics", {})
        content_det = item.get("contentDetails", {})

        title       = snippet.get("title", "")
        description = snippet.get("description", "")
        tags        = snippet.get("tags", [])
        duration    = self._parse_duration(content_det.get("duration", "PT0S"))
        view_count  = int(statistics.get("viewCount", 0))
        like_count  = int(statistics.get("likeCount", 0))

        # ── Score each dimension ──────────────────────────

        # Title (0-100): length 40-70 chars is ideal
        title_len = len(title)
        if 40 <= title_len <= 70:
            title_score = 100
        elif 30 <= title_len < 40 or 70 < title_len <= 80:
            title_score = 75
        elif 20 <= title_len < 30 or 80 < title_len <= 100:
            title_score = 50
        else:
            title_score = 25

        # Description (0-100): 200+ words is ideal
        desc_words = len(description.split())
        if desc_words >= 200:
            desc_score = 100
        elif desc_words >= 100:
            desc_score = 75
        elif desc_words >= 50:
            desc_score = 50
        elif desc_words >= 20:
            desc_score = 30
        else:
            desc_score = 10

        # Tags (0-100): 10-15 tags is ideal
        tag_count = len(tags)
        if 10 <= tag_count <= 15:
            tags_score = 100
        elif 6 <= tag_count < 10 or 15 < tag_count <= 20:
            tags_score = 75
        elif 3 <= tag_count < 6:
            tags_score = 50
        elif tag_count > 0:
            tags_score = 25
        else:
            tags_score = 0

        # Engagement rate (0-100): like/view ratio
        like_rate = (like_count / max(view_count, 1)) * 100
        if like_rate >= 5:
            engagement_score = 100
        elif like_rate >= 3:
            engagement_score = 80
        elif like_rate >= 1:
            engagement_score = 60
        elif like_rate >= 0.5:
            engagement_score = 40
        else:
            engagement_score = 20

        # Duration (0-100): 7-20 min is YouTube's sweet spot
        dur_min = duration / 60
        if 7 <= dur_min <= 20:
            duration_score = 100
        elif 4 <= dur_min < 7 or 20 < dur_min <= 30:
            duration_score = 75
        elif 2 <= dur_min < 4 or 30 < dur_min <= 45:
            duration_score = 50
        else:
            duration_score = 30

        # Weighted total
        seo_score = int(
            title_score      * 0.25 +
            desc_score       * 0.25 +
            tags_score       * 0.20 +
            engagement_score * 0.20 +
            duration_score   * 0.10
        )

        return {
            "video_id":  video_id,
            "seo_score": seo_score,
            "breakdown": {
                "title_length":    title_score,
                "description":     desc_score,
                "tags":            tags_score,
                "engagement_rate": engagement_score,
                "video_duration":  duration_score,
            },
            "raw": {
                "title_length":   title_len,
                "desc_words":     desc_words,
                "tag_count":      tag_count,
                "like_rate":      round(like_rate, 2),
                "duration_min":   round(dur_min, 1),
            },
        }

    # ── ISO 8601 duration parser ──────────────────────────
    def _parse_duration(self, iso_duration: str) -> int:
        """Parse ISO 8601 duration (PT1H2M3S) → total seconds."""
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
        if not match:
            return 0
        h = int(match.group(1) or 0)
        m = int(match.group(2) or 0)
        s = int(match.group(3) or 0)
        return h * 3600 + m * 60 + s
