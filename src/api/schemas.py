# src/api/schemas.py
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


class RagRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)


class RagResponse(BaseModel):
    answer: str
    sources: list[RetrievedChunk]
    usage: dict = Field(default_factory=dict)