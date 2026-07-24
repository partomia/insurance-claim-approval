from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = f"sqlite:///{Path(__file__).parent / 'insurance.db'}"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "cloudera-insurance-secret-key-for-demo"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days access token
    jwt_refresh_days: int = 30  # refresh token stored in DB

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # auto = try Celery, fallback to in-process pipeline; sync = always in-process
    claim_processing_mode: str = "auto"

    chroma_db_path: str = str(Path(__file__).parent / "chroma_db")
    chroma_collection_name: str = "insurance_policies"
    upload_dir: str = str(Path(__file__).parent / "storage")

    fraud_escalate_threshold: float = 0.75
    fraud_review_threshold: float = 0.40
    evidence_review_threshold: float = 0.55
    early_claim_days: int = 14
    early_claim_amount_thresholds: dict[str, float] = {
        "Health": 5000.0,
        "Auto": 10000.0,
        "Home": 7500.0,
    }
    human_review_amount_threshold: float = 500_000.0
    confidence_review_threshold: float = 0.60

    max_upload_size_mb: int = 25
    agent_invite_code: str = "CLOUDERA2026"

    # Set when running behind Cloudera CML port proxy, e.g. ROOT_PATH=/proxy/7878
    root_path: str = ""

    # Comma-separated browser origins allowed to call the API (required with cookies/auth)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if not raw:
            return ["http://localhost:5173", "http://127.0.0.1:5173"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
