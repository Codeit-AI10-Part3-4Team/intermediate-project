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
    # Chroma 벡터 DB 경로 — use_mock=False에서 Orchestrator에 주입되는 단일 통로.
    # (.env의 APP_CHROMA_DIR로 재정의. 코드 곳곳의 기본값 대신 여기를 신뢰할 것.)
    chroma_dir: str = "/data/vector_db/vector_db_v10"
