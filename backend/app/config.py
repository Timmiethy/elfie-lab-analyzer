from pathlib import Path

try:
    from pydantic_settings import BaseSettings
except ModuleNotFoundError:  # pragma: no cover - fallback for limited test envs
    from pydantic import BaseModel

    class BaseSettings(BaseModel):
        """Lightweight fallback when pydantic-settings is unavailable."""

        pass


_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://elfie:elfie@localhost:5432/elfie_labs"
    database_url_sync: str = "postgresql://elfie:elfie@localhost:5432/elfie_labs"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    # File upload limits
    max_upload_size_mb: int = 20
    max_pdf_pages: int = 30
    allowed_extensions: list[str] = ["pdf", "png", "jpg", "jpeg", "webp"]

    # Qwen / explanation adapter
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    qwen_vl_model: str = "qwen-vl-max"

    # Terminology
    loinc_path: Path = _REPO_ROOT / "data" / "loinc"
    terminology_snapshot_path: Path = _REPO_ROOT / "data" / "loinc"
    alias_tables_path: Path = _REPO_ROOT / "data" / "alias_tables"
    ucum_path: Path = _REPO_ROOT / "data" / "ucum"

    # Artifact storage
    artifact_store_path: Path = _REPO_ROOT / "artifacts"
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

    model_config = {"env_file": str(_REPO_ROOT / ".env"), "env_prefix": "ELFIE_"}


settings = Settings()
