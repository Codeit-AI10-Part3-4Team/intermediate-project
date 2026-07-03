# src/api/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")

    app_name: str = "RFP RAG API"
    use_mock: bool = True  # 목업 모드 사용 여부
    default_top_k: int = 5
    log_level: str = "INFO"
    # 설정 시 회전 파일 핸들러 추가 (예: /var/log/rfp/api.log). 미설정이면 stdout만.
    log_file: str | None = None
