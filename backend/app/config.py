from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic_settings import SettingsConfigDict

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings as _BaseSettings
else:
    try:
        from pydantic_settings import BaseSettings as _BaseSettings
    except ImportError:  # pragma: no cover - fallback for limited test envs

        class _BaseSettings(BaseModel):  # type: ignore
            pass


class Settings(_BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://elfie:elfie@localhost:5432/elfie_labs"
    database_url_sync: str = "postgresql://elfie:elfie@localhost:5432/elfie_labs"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]
    cors_allow_credentials: bool = False

    # File upload limits
    max_upload_size_mb: int = 20
    max_pdf_pages: int = 30
    pdf_render_dpi: int = 96
    pdf_render_concurrency: int = 2
    max_pdf_render_bytes: int = 256 * 1024 * 1024
    pdf_render_timeout_s: float = 30.0
    allowed_extensions: list[str] = ["pdf", "png", "jpg", "jpeg", "webp"]

    # Qwen / explanation adapter
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    qwen_vl_model: str = "qwen-vl-max"

    # Auth
    supabase_jwt_secret: str = ""
    # Dev-only: bypass JWT validation and return mock UUID when auth header is
    # missing, expired, or invalid. NEVER enable in production.
    dev_auth_bypass: bool = False

    # Terminology
    loinc_path: Path = Path("data/loinc")
    terminology_snapshot_path: Path = Path("data/loinc")
    alias_tables_path: Path = Path("data/alias_tables")
    ucum_path: Path = Path("data/ucum")

    # Artifact storage
    artifact_store_path: Path = Path("artifacts")
    upload_retention_days: int = 30
    artifact_retention_days: int = 30

    # Policy versions
    rule_pack_version: str = "0.1.0"
    severity_policy_version: str = "0.1.0"
    nextstep_policy_version: str = "0.1.0"
    critical_value_source_signed_off: bool = False

    # Operational runtime
    max_job_retries: int = 2

    # Image beta lane toggle
    image_beta_enabled: bool = False

    # Debug mode — enables PHI debug dumps; never enable in production
    debug: bool = False
    # Second-gate PHI artifact dump (debug extraction JSON + embedded raw rows).
    # Both `debug` and this flag must be true to write debug artifacts. Default
    # off so setting ELFIE_DEBUG=true for general logging never leaks PHI.
    allow_debug_artifacts: bool = False

    # VLM quality gate — rows with confidence below this are discarded
    min_vlm_confidence: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_prefix="ELFIE_", extra="ignore")


settings = Settings()
