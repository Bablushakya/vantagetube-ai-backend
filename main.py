"""
main.py — FastAPI application entry point


VantageTube AI — Backend API + Frontend on single port 8000

URL Map:
  http://localhost:8000/              → index.html (landing)
  http://localhost:8000/auth.html     → auth.html (login/register)
  http://localhost:8000/pages/        → pages served via StaticFiles
  http://localhost:8000/css/          → CSS assets
  http://localhost:8000/js/           → JS assets
  http://localhost:8000/assets/       → images/icons
  http://localhost:8000/api/          → REST API
  http://localhost:8000/api/docs      → Swagger UI

IMPORTANT: Open http://localhost:8000  (NOT http://0.0.0.0:8000)
           0.0.0.0 is uvicorn's bind address — use localhost in browser.
"""
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

# Force UTF-8 stdout so emoji in startup banner work on Windows (cp1252 terminals)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder

from app.core.config import settings
from app.core.supabase_client import init_supabase
from app.api import auth, youtube, videos, ai, trending, profile, settings as settings_router, api_keys

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("vantagetube")

# ── Frontend path ──────────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# ── Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 VantageTube AI starting — open http://localhost:8000 in your browser")
    init_supabase()
    logger.info("✅ Supabase client initialised")
    if FRONTEND_DIR.exists():
        logger.info(f"📁 Serving frontend from: {FRONTEND_DIR}")
    else:
        logger.warning(f"⚠️  Frontend directory not found: {FRONTEND_DIR}")
    yield
    logger.info("🛑 VantageTube AI backend shutting down")


# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title="VantageTube AI API",
    description="AI-powered YouTube creator assistant",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5050",
        "http://127.0.0.1:5050",
    ] + settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request timing middleware ─────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    if request.url.path.startswith("/api"):
        logger.info(f"{request.method} {request.url.path} → {response.status_code} ({ms:.1f}ms)")
    return response


# ── Global error handler ──────────────────────────────────
@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Log Pydantic 422 errors to terminal so you can see exactly which field failed."""
    errors = exc.errors()
    for e in errors:
        loc = " → ".join(str(x) for x in e.get("loc", []))
        logger.warning(f"422 Validation [{request.method} {request.url.path}] field '{loc}': {e['msg']}")
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(errors)},
    )


# ── API Routers ───────────────────────────────────────────
PREFIX = "/api"
app.include_router(auth.router,            prefix=f"{PREFIX}/auth",    tags=["Auth"])
app.include_router(youtube.router,         prefix=f"{PREFIX}/youtube",  tags=["YouTube"])
app.include_router(videos.router,          prefix=f"{PREFIX}/videos",   tags=["Videos"])
app.include_router(ai.router,              prefix=f"{PREFIX}/ai",       tags=["AI"])
app.include_router(trending.router,        prefix=f"{PREFIX}/trending", tags=["Trending"])
app.include_router(profile.router,         prefix=f"{PREFIX}/profile",  tags=["Profile"])
app.include_router(settings_router.router, prefix=f"{PREFIX}/settings", tags=["Settings"])
app.include_router(api_keys.router,        prefix=f"{PREFIX}/api-keys", tags=["API Keys"])


# ── Health ────────────────────────────────────────────────
@app.get("/api/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": "1.0.0", "env": settings.APP_ENV}


# ── Frontend: root HTML files ─────────────────────────────
@app.get("/", include_in_schema=False)
async def serve_index():
    f = FRONTEND_DIR / "index.html"
    return FileResponse(str(f)) if f.exists() else JSONResponse({"msg": "visit /api/docs"})


@app.get("/auth.html", include_in_schema=False)
async def serve_auth():
    return FileResponse(str(FRONTEND_DIR / "auth.html"))


# ── Frontend: static asset mounts ────────────────────────
# IMPORTANT: mounts must be registered AFTER all @app.get routes
# so the catch-all routes above take priority over static file 404s.
if FRONTEND_DIR.exists():
    app.mount("/css",    StaticFiles(directory=str(FRONTEND_DIR / "css")),   name="css")
    app.mount("/js",     StaticFiles(directory=str(FRONTEND_DIR / "js")),    name="js")
    app.mount("/pages",  StaticFiles(directory=str(FRONTEND_DIR / "pages"), html=True), name="pages")

    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


# ── Dev entry point ───────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*55)
    print("  ✅  Server started!  Open in browser:")
    print("  👉  http://localhost:8000")
    print("  📖  API docs: http://localhost:8000/api/docs")
    print("="*55 + "\n")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",   # bind all interfaces — use localhost in browser!
        port=8000,
        reload=True,
        reload_dirs=[str(Path(__file__).parent)],
        log_level="info",
    )
