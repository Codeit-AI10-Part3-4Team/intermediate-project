# src/api/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")
    
    app_name: str = "RFP RAG API"
    use_mock: bool = True # 목업 모드 사용 여부
    default_top_k: int = 5