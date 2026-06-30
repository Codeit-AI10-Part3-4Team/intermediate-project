from langchain_chroma import Chroma
from rank_bm25 import BM25Okapi
from kiwipiepy import Kiwi
import numpy as np
from rag_core.schemas import Chunk, RetrievedChunk
from rag_core.embedding.embedder import load_embedding_model

COLLECTION_NAME = "rfp_docs"
BATCH_SIZE      = 500
TOP_K_CANDIDATE = 100
RRF_K           = 60

_kiwi = Kiwi()

def _tokenize(text: str) -> list[str]:
    return [token.form for token in _kiwi.tokenize(text)]

class Retriever:
    def __init__(
        self,
        embedding_model_name: str = "bge-m3",
        chroma_dir: str = "./data/vector_db_v4",
        device: str = "cuda",
    ):
        self.embedding_model = load_embedding_model(embedding_model_name)
        self.vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=self.embedding_model,
            persist_directory=chroma_dir,
        )
        self.bm25: BM25Okapi | None = None
        self.text_to_idx: dict[str, int] = {}

    def load(self) -> None:
        all_docs = self.vectorstore.get()
        all_texts = all_docs["documents"]
        if not all_texts:
            raise RuntimeError("Chroma DB가 비어 있습니다. index()를 먼저 호출하세요.")
        print(f"Chroma에서 {len(all_texts)}개 청크 로드 중...")
        self.bm25 = BM25Okapi([_tokenize(t) for t in all_texts])
        self.text_to_idx = {text: i for i, text in enumerate(all_texts)}
        print("BM25 완료")

    def index(self, chunks: list[Chunk]) -> None:
        all_texts = [c.text for c in chunks]
        all_metas = [c.metadata for c in chunks]

        for start in range(0, len(all_texts), BATCH_SIZE):
            end = start + BATCH_SIZE
            self.vectorstore.add_texts(
                texts=all_texts[start:end],
                metadatas=all_metas[start:end],
            )
            print(f"  저장 완료: {min(end, len(all_texts))}/{len(all_texts)}")

        print(f"\nChroma 저장 완료 (총 {self.vectorstore._collection.count()}개 청크)")

        print("BM25 인덱스 빌드 중...")
        self.bm25 = BM25Okapi([_tokenize(t) for t in all_texts])
        self.text_to_idx = {text: i for i, text in enumerate(all_texts)}
        print("BM25 완료")

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        if self.bm25 is None:
            raise RuntimeError("BM25 인덱스가 없습니다. index()를 먼저 호출하세요.")

        vec_hits = self.vectorstore.similarity_search_with_relevance_scores(
            query, k=TOP_K_CANDIDATE
        )
        if not vec_hits:
            return []

        bm25_scores = self.bm25.get_scores(_tokenize(query))
        bm25_top_indices = np.argsort(-bm25_scores)[:TOP_K_CANDIDATE]
        bm25_rank = {idx: rank + 1 for rank, idx in enumerate(bm25_top_indices)}

        combined = []
        for vec_rank, (doc, _) in enumerate(vec_hits):
            idx = self.text_to_idx.get(doc.page_content)
            b_rank = bm25_rank.get(idx, TOP_K_CANDIDATE + 1) if idx is not None else TOP_K_CANDIDATE + 1
            rrf_score = 1 / (RRF_K + vec_rank + 1) + 1 / (RRF_K + b_rank)
            combined.append((doc, rrf_score))

        combined.sort(key=lambda x: x[1], reverse=True)

        retrieved = []
        for doc, score in combined[:top_k]:
            chunk = Chunk(
                chunk_id=doc.metadata.get("block_id", ""),
                doc_id=doc.metadata.get("doc_id", ""),
                text=doc.page_content,
                metadata=doc.metadata,
            )
            retrieved.append(RetrievedChunk(chunk=chunk, score=score))

        return retrieved