# src/api/lifespan.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from api.config import Settings
from api.logging_config import setup_logging
from api.mock import MockRetriever, MockLLM, MockOrchestrator, MockSuitabilityChecker
from rag_core.checker import RfpSuitabilityChecker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    setup_logging(level=settings.log_level, log_file=settings.log_file)

    if settings.use_mock:
        app.state.retriever = MockRetriever()
        app.state.llm = MockLLM()
        app.state.orchestrator = MockOrchestrator()
        app.state.suitability_checker = MockSuitabilityChecker()
    else:
        # 실제 LangGraph Orchestrator 연결 — 경로는 Settings가 단일 원천 (주입)
        from rag_core.orchestration.orchestrator import LangGraphOrchestrator

        app.state.orchestrator = LangGraphOrchestrator(chroma_dir=settings.chroma_dir)
        app.state.suitability_checker = RfpSuitabilityChecker(orchestrator=app.state.orchestrator)

    yield

    # shutdown 시 정리 작업
