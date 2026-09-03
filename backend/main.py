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
    # so a bad API path doesn't silently return the SPA shell.
    _api_prefixes = ("/api", "/auth", "/agent", "/insurer", "/docs", "/openapi.json", "/redoc")

    @app.exception_handler(StarletteHTTPException)
    async def _spa_fallback(request, exc: StarletteHTTPException):
        # For unknown GET routes that aren't API calls, serve the SPA shell so
        # client-side routing (React Router) can handle the path on reload.
        if (
            exc.status_code == 404
            and request.method == "GET"
            and not request.url.path.startswith(_api_prefixes)
        ):
            return FileResponse(_index_file)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.get("/{full_path:path}", include_in_schema=False)
    def _serve_spa(full_path: str):
        # Serve a real static file if it exists (favicon, manifest, etc.),
        # otherwise the SPA shell.
        candidate = _frontend_dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(_index_file)

else:
    # API-only mode (no built frontend present): keep a JSON root.
    @app.get("/")
    def read_root():
        return {
            "message": "ClaimCopilot API — AI Insurance Claim Assistant",
            "docs": "/docs",
            "health": "ok",
        }
