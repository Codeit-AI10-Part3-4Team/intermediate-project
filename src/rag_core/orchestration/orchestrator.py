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
        # 멀티턴용(체크포인터 有)과 일회성용(체크포인터 無) 두 그래프를 준비한다.
        # session_id 없는 요청은 체크포인터 없는 그래프로 처리해 상태 누적을 원천 차단.
        from rag_core.orchestration.langgraph_router import build_graph

        self._app = build_graph(chroma_dir=resolved_chroma_dir, use_checkpointer=True)
        self._app_stateless = build_graph(chroma_dir=resolved_chroma_dir, use_checkpointer=False)

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
        # session_id 있으면 멀티턴(체크포인터 有) 그래프, 없으면 일회성(체크포인터 無) 그래프.
        # 체크포인터 없는 그래프는 상태를 저장하지 않아 메모리 누수가 원천적으로 없다.
        if session_id:
            app = self._app
            thread_id = session_id
            config = {"configurable": {"thread_id": thread_id}}
        else:
            app = self._app_stateless
            thread_id = ""  # 일회성 요청은 세션 추적 안 함
            config = {}

        state_input: dict = {
            "question": query,
            "history": history or [],
        }
        if company_info:
            state_input["company_info"] = company_info

        result = app.invoke(state_input, config=config)

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
            except Exception as e:
                print(f"[Orchestrator] source 변환 오류 (skip): {e}")

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
