# src/api/interfaces.py
from typing import Protocol, runtime_checkable

from .schemas import Document, Chunk, RetrievedChunk, RagResponse


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