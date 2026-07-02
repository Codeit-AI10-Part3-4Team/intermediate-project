"""
src/rag_core/orchestration/orchestrator.py

LangGraph 기반 Orchestrator — FastAPI lifespan에서 주입되는 실제 구현체.
rag_core.interfaces.Orchestrator Protocol을 구조적으로 충족한다.

사용법 (lifespan.py):
    from rag_core.orchestration.orchestrator import LangGraphOrchestrator
    app.state.orchestrator = LangGraphOrchestrator()
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

from rag_core.schemas import RagResponse, RetrievedChunk, Chunk


class LangGraphOrchestrator:
    """
    LangGraph Router를 FastAPI Orchestrator Protocol에 맞게 감싸는 어댑터.

    - run(query, top_k) → RagResponse
    - session_id 없으면 랜덤 thread_id 사용 (stateless)
    - session_id 있으면 멀티턴 유지 (stateful)
    """

    def __init__(
        self,
        chroma_dir: Optional[str] = None,
    ):
        resolved_chroma_dir: str = (
            chroma_dir
            if chroma_dir is not None
            else (os.getenv("CHROMA_DIR") or "/data/vector_db/vector_db_v4")
        )

        # LangGraph 앱 초기화 (Retriever + Ollama 포함)
        from rag_core.orchestration.langgraph_router import build_graph

        self._app = build_graph(chroma_dir=resolved_chroma_dir)

    def run(
        self,
        query: str,
        top_k: int = 10,
        session_id: Optional[str] = None,
        history: Optional[list] = None,
        company_info: Optional[str] = None,
    ) -> RagResponse:
        """
        LangGraph 파이프라인 실행 후 RagResponse로 변환.

        Args:
            query: 사용자 질문
            top_k: 검색할 청크 수 (Router 내부에서 조정)
            session_id: 멀티턴 세션 ID (없으면 랜덤 생성)
            history: 이전 대화 히스토리
            company_info: 입찰 적합도 분석 시 회사 정보

        Returns:
            RagResponse(answer, sources, usage)
        """
        thread_id = session_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        state_input: dict = {
            "question": query,
            "history": history or [],
        }
        if company_info:
            state_input["company_info"] = company_info

        result = self._app.invoke(state_input, config=config)

        answer = result.get("answer", "")
        retrieved_sources = result.get("retrieved_sources", [])
        history_out = result.get("history", [])

        # sources → RetrievedChunk 변환
        sources = []
        for src in retrieved_sources:
            try:
                chunk = Chunk(
                    chunk_id=src.get("chunk_id", ""),
                    doc_id=src.get("doc_id", ""),
                    text=src.get("text", ""),
                    metadata=src.get("metadata", {}),
                )
                sources.append(RetrievedChunk(chunk=chunk, score=src.get("score", 0.0)))
            except Exception:
                pass

        return RagResponse(
            answer=answer,
            sources=sources,
            usage={
                "thread_id": thread_id,
                "question_type": result.get("question_type", ""),
                "history_length": len(history_out),
                "related_questions": result.get("related_questions", ""),
                "style_prompt": result.get("style_prompt", ""),
            },
        )
