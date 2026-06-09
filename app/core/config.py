from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: SecretStr
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    pinecone_api_key: SecretStr
    pinecone_environment: str
    pinecone_index_name: str = "chatbot-index"

    api_key_secret: SecretStr
    sentry_dsn: str = ""
    log_level: str = "INFO"
    allowed_origins: list[str] = ["*"]

    similarity_threshold: float = 0.45
    top_k_results: int = 3
    max_tokens_response: int = 1024

    cache_ttl_days: int = 7
    cache_db_path: str = "cache.db"

    woo_ck: str = ""
    woo_cs: str = ""
    euro_rate: float = 52.0  # Зможемо оновлювати динамічно пізніше
    margin_threshold: float = 200.0

    root_path: str = ""

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    @field_validator("openai_api_key")
    @classmethod
    def validate_openai_api_key(cls, v: SecretStr) -> SecretStr:
        if not v.get_secret_value().startswith("sk-"):
            raise ValueError("openai_api_key must start with 'sk-'")
        return v

    @field_validator("pinecone_environment")
    @classmethod
    def validate_pinecone_environment(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("pinecone_environment cannot be empty")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg] # pyright: ignore[reportCallIssue]
