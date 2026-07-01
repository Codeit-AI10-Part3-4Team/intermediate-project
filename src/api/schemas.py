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
