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


@app.get("/")
def read_root():
    return {
        "message": "ClaimCopilot API — AI Insurance Claim Assistant",
        "docs": "/docs",
        "health": "ok",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}
