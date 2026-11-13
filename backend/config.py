from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')

    app_env: Literal['local', 'public', 'cloud', 'test'] = 'local'
    host: str = '127.0.0.1'
    port: int = Field(default=8000, ge=1, le=65535)
    storage_root: Path = ROOT / 'storage'
    max_upload_mb: int | None = Field(default=None, ge=1, le=25)
    max_rows: int = Field(default=50000, ge=1, le=200000)
    max_columns: int = Field(default=100, ge=1, le=500)
    max_sessions: int = Field(default=50, ge=1, le=200)
    max_versions: int = Field(default=30, ge=2, le=100)
    max_storage_mb: int = Field(default=512, ge=25, le=4096)
    session_ttl_minutes: int = Field(default=60, ge=1, le=1440)
    job_timeout_seconds: int = Field(default=120, ge=1, le=600)
    ai_enabled: bool = False
    ai_zero_cost_mode: bool = True
    openrouter_api_key: SecretStr = SecretStr('')
    openrouter_model: str = 'openrouter/free'
    ai_request_timeout_seconds: int = Field(default=15, ge=1, le=30)
    ai_max_retries: int = Field(default=1, ge=0, le=1)
    ai_cache_enabled: bool = True
    ai_daily_request_limit: int = Field(default=45, ge=0, le=45)

    @model_validator(mode='after')
    def public_limits(self):
        if self.app_env in {'public', 'cloud'}:
            self.max_upload_mb = min(self.max_upload_mb or 5, 5)
            self.max_rows = min(self.max_rows, 10000)
            self.max_columns = min(self.max_columns, 50)
            self.max_sessions = min(self.max_sessions, 10)
            self.max_storage_mb = min(self.max_storage_mb, 256)
        return self

    @property
    def limits(self) -> dict:
        return {
            'max_upload_bytes': (self.max_upload_mb or 25) * 1024 * 1024,
            'max_rows': self.max_rows,
            'max_columns': self.max_columns,
            'max_uncompressed_bytes': (30 if self.app_env in {'public', 'cloud'} else 100) * 1024 * 1024,
            'max_expansion_ratio': 100,
        }
