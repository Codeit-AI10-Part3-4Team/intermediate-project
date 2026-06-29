# src/api/lifespan.py

from contextlib import asynccontextmanager
from fastapi import FastAPI
from api.config import Settings
from api.mock import MockRetriever, MockLLM, MockOrchestrator


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    if settings.use_mock:
        app.state.retriever = MockRetriever()
        app.state.llm = MockLLM()
        app.state.orchestrator = MockOrchestrator()  # 라우터가 주입받는 대상
    # else: 실제 ChromaRetriever / LLM / Orchestrator 연결
    yield
    # shutdown 시 필요한 정리 작업 수행 (예: DB 연결 종료, 리소스 해제 등)
