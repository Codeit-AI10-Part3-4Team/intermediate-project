# src/api/lifespan.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from api.config import Settings
from api.mock import MockRetriever, MockLLM, MockOrchestrator, MockSuitabilityChecker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()

    if settings.use_mock:
        app.state.retriever = MockRetriever()
        app.state.llm = MockLLM()
        app.state.orchestrator = MockOrchestrator()
        app.state.suitability_checker = MockSuitabilityChecker()
    else:
        # 실제 LangGraph Orchestrator 연결
        from rag_core.orchestration.orchestrator import LangGraphOrchestrator

        app.state.orchestrator = LangGraphOrchestrator()
        app.state.suitability_checker = MockSuitabilityChecker()  # 추후 실제 구현으로 교체

    yield

    # shutdown 시 정리 작업
