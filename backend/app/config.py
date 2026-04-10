from pathlib import Path

from pydantic_settings import BaseSettings


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
    loinc_path: Path = Path("data/loinc")
    alias_tables_path: Path = Path("data/alias_tables")
    ucum_path: Path = Path("data/ucum")

    # Artifact storage
    artifact_store_path: Path = Path("artifacts")

    # Policy versions
    rule_pack_version: str = "0.1.0"
    severity_policy_version: str = "0.1.0"
    nextstep_policy_version: str = "0.1.0"

    # Image beta lane toggle
    image_beta_enabled: bool = False

    model_config = {"env_file": ".env", "env_prefix": "ELFIE_"}


settings = Settings()
