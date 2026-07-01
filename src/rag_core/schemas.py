# src/rag_core/schemas.py
# 파이프라인이 주고받는 도메인 모델의 단일 원천(single source of truth).
# api 등 서빙 레이어는 이 모델을 import해서 사용한다 (의존 방향: api -> rag_core).
from pydantic import BaseModel, Field


class Document(BaseModel):
    doc_id: str
    source_path: str
    text: str
    metadata: dict = Field(default_factory=dict)


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    metadata: dict = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float


class RagResponse(BaseModel):
    answer: str
    sources: list[RetrievedChunk]
    usage: dict = Field(default_factory=dict)


class SuitabilityResult(BaseModel):
    # 업로드 문서의 RFP 적합성 검사 결과. 업로드 데이터는 저장하지 않고(transient)
    # 이 결과만 반환한다 (docs/architecture.md §4).
    is_suitable: bool
    score: float
    reasons: list[str] = Field(default_factory=list)  # 누락 항목·형식 등 피드백
    sources: list[RetrievedChunk] = Field(default_factory=list)  # 참조 코퍼스 비교 근거
    usage: dict = Field(default_factory=dict)
