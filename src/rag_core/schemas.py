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
