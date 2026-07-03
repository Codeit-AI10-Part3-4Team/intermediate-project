# src/api/schemas.py
# HTTP 입출력 전용 DTO만 둔다.
# 도메인 모델(Document/Chunk/RetrievedChunk/RagResponse)과 계약(interfaces)은
# src/rag_core 가 단일 원천이다. 응답 모델은 그대로 재사용한다 (의존 방향: api -> rag_core).
from pydantic import BaseModel, Field

from rag_core.schemas import RagResponse, SuitabilityResult  # re-export for routers

__all__ = ["RagRequest", "RagResponse", "SuitabilityResult"]


class RagRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    # 멀티턴: 이전 응답 usage.thread_id를 그대로 보내면 같은 세션으로 이어진다.
    session_id: str | None = Field(default=None, max_length=64)
    # 입찰 적합도 분석 시 회사 정보 (질문 유형이 bid_analysis일 때 사용됨).
    company_info: str | None = Field(default=None, max_length=4000)
