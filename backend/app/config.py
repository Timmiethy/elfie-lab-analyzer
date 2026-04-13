from pathlib import Path

try:
    from pydantic_settings import BaseSettings
except ModuleNotFoundError:  # pragma: no cover - fallback for limited test envs
    from pydantic import BaseModel

    class BaseSettings(BaseModel):
        """Lightweight fallback when pydantic-settings is unavailable."""

        pass

try:
    from pydantic import AliasChoices, Field
except ImportError:  # pragma: no cover
    class AliasChoices:  # type: ignore[misc]
        def __init__(self, *choices: str):
            self.choices = choices

    def Field(default=None, **kwargs):  # type: ignore[misc]
        return default  # noqa: ARG001


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

    # v12 parser-migration: trusted born-digital primary backend
    pymupdf_enabled: bool = True
    pymupdf_version_pin: str = "1.27.x"

    # v12: pdfplumber is debug/forensic-only, NOT production primary
    pdfplumber_debug_only: bool = True

    # v12 OCR / image lane: qwen-vl-ocr-2025-11-20 primary
    qwen_ocr_enabled: bool = True
    qwen_ocr_model: str = "qwen-vl-ocr-2025-11-20"
    qwen_ocr_api_key: str = ""
    qwen_ocr_api_base: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("ELFIE_QWEN_OCR_API_BASE", "ELFIE_QWEN_OCR_BASE_URL"),
    )
    qwen_ocr_timeout_seconds: int = 120

    # v12: deprecated image-beta backends disabled by default
    surya_enabled: bool = False
    doctr_enabled: bool = False

    # v12: image-beta is preview-only, never silently promotes to trusted
    image_beta_promotion_allowed: bool = False

    # Terminology
    loinc_path: Path = _REPO_ROOT / "data" / "loinc"
    terminology_snapshot_path: Path = _REPO_ROOT / "data" / "loinc"
    alias_tables_path: Path = _REPO_ROOT / "data" / "alias_tables"
    ucum_path: Path = _REPO_ROOT / "data" / "ucum"
    family_config_registry_path: Path = _REPO_ROOT / "data" / "family_configs" / "document_family_registry_v1.json"

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

    # Image beta lane toggle (legacy, superseded by v12 image_beta_promotion_allowed)
    image_beta_enabled: bool = False

    model_config = {"env_file": str(_REPO_ROOT / ".env"), "env_prefix": "ELFIE_"}


settings = Settings()
