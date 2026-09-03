from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from db_init import ensure_schema
from database import SessionLocal, engine
import models  # noqa: F401
from routers import agent, agent_assistant, agent_auth, agents, assistant, auth, claims, dashboard, insurer, insurer_auth, kyc, policies, policy_connect, rag

settings = get_settings()

ensure_schema()

from services.expert_queue_service import backfill_unassigned_queue_claims
from services.insurer_demo_service import ensure_demo_insurer

_db = SessionLocal()
try:
    backfill_unassigned_queue_claims(_db)
    ensure_demo_insurer(_db)
finally:
    _db.close()

Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path(settings.chroma_db_path).mkdir(parents=True, exist_ok=True)

from rag.chroma_store import chroma_store  # noqa: E402 — ensure collection init on startup

chroma_store.ensure_collection()

app = FastAPI(
    title="ClaimCopilot API",
    description="AI-powered insurance claim assistant — predict approval before submission",
    version="2.0.0",
    root_path=settings.root_path,
)

cors_origins = settings.cors_origin_list()

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(agent_auth.router)
app.include_router(insurer_auth.router)
app.include_router(agent.router)
app.include_router(insurer.router)
app.include_router(agent_assistant.router)
app.include_router(agents.router)
app.include_router(claims.router)
app.include_router(dashboard.router)
app.include_router(policies.router)
app.include_router(kyc.router)
app.include_router(policy_connect.router)
app.include_router(assistant.router)
app.include_router(rag.router)


@app.get("/api/health")
def api_root():
    return {
        "message": "ClaimCopilot API — AI Insurance Claim Assistant",
        "docs": "/docs",
        "health": "ok",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


def _build_marker() -> str:
    """Short git SHA (or BUILD_MARKER env) so you can confirm the live version."""
    import os
    import subprocess

    env_marker = os.getenv("BUILD_MARKER", "").strip()
    if env_marker:
        return env_marker
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(Path(__file__).resolve().parent),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


_BUILD_MARKER = _build_marker()


@app.get("/api/version")
def api_version():
    """Deploy marker — hit this to confirm CML is running the current build.
    Also reports whether the SPA is served and which LLM provider/model is active.
    """
    return {
        "version": app.version,
        "build": _BUILD_MARKER,
        "serves_frontend": _frontend_dist is not None,
        "db_backend": settings.db_backend,
        "llm_model": settings.groq_model if not settings.uses_custom_llm_endpoint else settings.llm_model,
        "llm_provider": "openai_compatible" if settings.uses_custom_llm_endpoint else "groq",
    }


@app.get("/api/llm/health")
def llm_health():
    """Live LLM diagnostic — pings the active model and returns the real error."""
    from services.llm_service import llm_service

    return llm_service.health()


# --------------------------------------------------------------------------- #
# Serve the built frontend (single same-origin CML Application)
# --------------------------------------------------------------------------- #
def _resolve_frontend_dist() -> Path | None:
    if not settings.serve_frontend:
        return None
    if settings.frontend_dist_dir:
        candidate = Path(settings.frontend_dist_dir)
        return candidate if (candidate / "index.html").exists() else None
    # Auto-detect ../frontend/dist relative to the backend package.
    candidate = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    return candidate if (candidate / "index.html").exists() else None


_frontend_dist = _resolve_frontend_dist()

if _frontend_dist is not None:
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as StarletteHTTPException

    # Hashed build assets (JS/CSS/img) live under /assets.
    _assets_dir = _frontend_dist / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    _index_file = str(_frontend_dist / "index.html")

    @app.get("/", include_in_schema=False)
    def _serve_index():
        return FileResponse(_index_file)

    # API route prefixes that must 404 as JSON (never fall back to index.html),
    # so a bad/unauthenticated API path can't silently return the SPA shell and
    # crash the frontend's JSON parsing.
    _api_prefixes = ("/api", "/auth", "/agent", "/insurer", "/docs", "/openapi.json", "/redoc")

    # NOTE: SPA fallback is handled ENTIRELY by the 404 exception handler below —
    # NOT by a catch-all GET route. A catch-all `/{full_path:path}` would match
    # unknown /api/* GETs and return 200 index.html, breaking API error handling.
    @app.exception_handler(StarletteHTTPException)
    async def _spa_fallback(request, exc: StarletteHTTPException):
        path = request.url.path
        is_api = path.startswith(_api_prefixes)

        # Only fall back to the SPA for browser GET navigations to non-API paths.
        if exc.status_code == 404 and request.method == "GET" and not is_api:
            # Serve a real static asset if one exists at that path (favicon,
            # manifest, robots.txt, etc.), otherwise the SPA shell so React
            # Router can handle the client-side route on reload.
            rel = path.lstrip("/")
            if rel:
                candidate = _frontend_dist / rel
                # Guard against path traversal outside the dist directory.
                try:
                    candidate.resolve().relative_to(_frontend_dist.resolve())
                    if candidate.is_file():
                        return FileResponse(str(candidate))
                except (ValueError, OSError):
                    pass
            return FileResponse(_index_file)

        # Everything else (all API errors) stays JSON.
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

else:
    # API-only mode (no built frontend present): keep a JSON root.
    @app.get("/")
    def read_root():
        return {
            "message": "ClaimCopilot API — AI Insurance Claim Assistant",
            "docs": "/docs",
            "health": "ok",
        }
