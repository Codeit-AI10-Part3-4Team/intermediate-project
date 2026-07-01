# src/rag_core/interfaces.py
# 파이프라인 각 단계가 따라야 할 계약(Protocol)의 단일 원천.
# Protocol = 구조적 타이핑이므로 구현체는 이 클래스를 상속할 필요가 없다
# (시그니처만 맞으면 자동으로 해당 타입으로 간주된다).
from typing import Protocol, runtime_checkable

from .schemas import Document, Chunk, RetrievedChunk, RagResponse, SuitabilityResult


@runtime_checkable
class Parser(Protocol):
    def parse(self, file_path: str) -> Document: ...


@runtime_checkable
class Chunker(Protocol):
    def chunk(self, document: Document) -> list[Chunk]: ...


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class Retriever(Protocol):
    def index(self, chunks: list[Chunk]) -> None: ...
    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]: ...


@runtime_checkable
class LLMClient(Protocol):
    def generate(self, prompt: str, *, temperature: float, max_tokens: int) -> str: ...


@runtime_checkable
class Orchestrator(Protocol):
    def run(self, query: str, top_k: int) -> RagResponse: ...


@runtime_checkable
class SuitabilityChecker(Protocol):
    # 업로드 문서(transient)의 RFP 적합성 판정: parse → embed → 참조 코퍼스 비교 → llm 판정.
    def check(self, file_path: str) -> SuitabilityResult: ...
