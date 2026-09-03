from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database backend selector — "sqlite" (default, local dev) or "impala" (CDP).
    db_backend: str = "sqlite"

    # SQLite (default local backend)
    database_url: str = f"sqlite:///{Path(__file__).parent / 'insurance.db'}"

    # Impala (CDP Data Warehouse) — used only when DB_BACKEND=impala
    impala_host: str = "go01-aws-rtdm-gateway.go01-dem.ylcu-atmi.cloudera.site"
    impala_port: int = 443
    impala_database: str = "default"
    impala_use_ssl: bool = True
    impala_auth_mechanism: str = "GSSAPI"
    impala_use_http_transport: bool = True
    impala_http_path: str = "go01-aws-rtdm/cdp-proxy-api/impala"
    impala_kerberos_service_name: str = "impala"
    impala_user: str = ""
    impala_password: str = ""

    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "cloudera-insurance-secret-key-for-demo"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    jwt_refresh_days: int = 30

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    claim_processing_mode: str = "auto"
    use_crewai_flow: bool = False

    chroma_db_path: str = str(Path(__file__).parent / "chroma_db")
    chroma_collection_name: str = "insurance_policies"
    upload_dir: str = str(Path(__file__).parent / "storage")

    fraud_escalate_threshold: float = 0.75
    fraud_review_threshold: float = 0.40
    evidence_review_threshold: float = 0.55
    early_claim_days: int = 14
    early_claim_amount_thresholds: dict[str, float] = {"Motor": 10000.0}
    human_review_amount_threshold: float = 500_000.0
    confidence_review_threshold: float = 0.60

    max_upload_size_mb: int = 25
    agent_invite_code: str = "CLOUDERA2026"
    root_path: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    assistant_recent_turn_limit: int = 8
    assistant_compaction_message_threshold: int = 16
    assistant_compaction_char_threshold: int = 6000
    assistant_summary_char_cap: int = 1500
    assistant_max_long_term_facts: int = 20
    assistant_history_limit: int = 30
    assistant_summary_max_tokens: int = 512
    assistant_ltm_extract_max_tokens: int = 256
    assistant_backfill_on_startup: bool = True

    @property
    def uses_impala(self) -> bool:
        return self.db_backend.strip().lower() == "impala"

    @property
    def uses_sqlite(self) -> bool:
        return not self.uses_impala

    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if not raw:
            return ["http://localhost:5173", "http://127.0.0.1:5173"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
