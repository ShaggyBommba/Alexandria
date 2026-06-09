from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class AppSettings(BaseModel):
    app_env: str = "development"
    app_name: str = "alexandria"
    app_version: str = "0.1.0"
    debug: bool = False
    api_host: str = "localhost"
    api_port: int = 8002
    mcp_host: str = "localhost"
    mcp_port: int = 9002
    worker_poll_interval: int = 3

class LoggingSettings(BaseModel):
    level: str = "INFO"
    json_output: bool = False
    file_handler_enabled: bool = True
    file_path_pattern: str = ".logs/{date}.log"
    stream_handler_enabled: bool = True
    stream_format: str = "[%(asctime)s] %(levelname)-8s %(message)s"
    stream_date_format: str = "%H:%M:%S"

class QueueSettings(BaseModel):
    """Configuration for durable queue processing."""

    enabled: bool = True
    max_attempts: int = 5
    batch_size: int = 25


class EmbeddingProvider(StrEnum):
    """Supported embedding provider adapters."""

    OPENAI = "openai"


class EmbeddingSettings(BaseModel):
    """Configuration for an OpenAI-compatible embedding endpoint."""

    provider: EmbeddingProvider = EmbeddingProvider.OPENAI
    base_url: str = Field(default="https://api.openai.com/v1", min_length=1)
    api_key: str | None = None
    model: str = Field(default="text-embedding-3-small", min_length=1)
    dimensions: int | None = Field(default=None, gt=0)
    timeout_seconds: float = Field(default=30.0, gt=0)


class SQLSettings(BaseModel):
    """Configuration for the database used by repositories."""

    host: str = "localhost"
    port: int = 5432
    user: str = "alexandria"
    password: str = "alexandria"
    database: str = "alexandria"
    ssl_mode: str | None = None

    @property
    def dsn(self) -> str:
        username = quote_plus(self.user)
        password = quote_plus(self.password)
        suffix = f"?sslmode={self.ssl_mode}" if self.ssl_mode else ""
        return f"postgresql://{username}:{password}@{self.host}:{self.port}/{self.database}{suffix}"

class Settings(BaseSettings):
    app: AppSettings = Field(default_factory=AppSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    database: SQLSettings = Field(default_factory=SQLSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)

    model_config = SettingsConfigDict(
        env_prefix="ALEXANDRIA_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )


@lru_cache()
def get_settings(env_file: str | Path = ".env") -> Settings:
    load_dotenv(env_file, override=False)
    settings = Settings()
    return settings
