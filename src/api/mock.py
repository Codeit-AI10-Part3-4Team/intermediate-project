# src/api/mock.py

# from rag_core.interfaces import Retriever, LLMClient
from rag_core.schemas import Chunk, RetrievedChunk, RagResponse, SuitabilityResult


class MockRetriever:
    def index(self, chunks: list[Chunk]) -> None:
        return None

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        chunk = Chunk(chunk_id="mock_1", doc_id="mock_doc", text="(mock) 관련 근거 청크")
        return [RetrievedChunk(chunk=chunk, score=0.99)][:top_k]


class MockLLM:
    def generate(self, prompt: str, *, temperature: float = 0.2, max_tokens: int = 2048) -> str:
        return "(mock) LLM 응답"


class MockOrchestrator:
    def run(self, query: str, top_k: int) -> RagResponse:
        chunk = Chunk(chunk_id="mock_1", doc_id="mock_doc", text="(mock) 관련 근거 청크")
        return RagResponse(
            answer="(mock) LLM 응답",
            sources=[RetrievedChunk(chunk=chunk, score=0.99)][:top_k],
            usage={},
        )


class MockSuitabilityChecker:
    def check(self, file_path: str) -> SuitabilityResult:
        chunk = Chunk(chunk_id="mock_1", doc_id="mock_corpus", text="(mock) 참조 코퍼스 근거 청크")
        return SuitabilityResult(
            is_suitable=True,
            score=0.87,
            reasons=["(mock) RFP 필수 항목 충족", "(mock) 유사 참조 문서와 정합"],
            sources=[RetrievedChunk(chunk=chunk, score=0.87)],
            usage={},
        )
