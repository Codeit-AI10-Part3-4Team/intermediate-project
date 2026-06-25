from langchain_chroma import Chroma
from sentence_transformers import CrossEncoder
from src.rag_core.schemas import Chunk, RetrievedChunk
from src.rag_core.embedding.embedder import load_embedding_model

COLLECTION_NAME  = "rfp_docs"
BATCH_SIZE       = 500
TOP_K_RETRIEVE   = 20

class Retriever:
    def __init__(
        self,
        embedding_model_name: str = "bge-m3",
        chroma_dir: str = "./data/vector_db_v4",
        reranker_model_name: str = "BAAI/bge-reranker-large",
        device: str = "cuda",
    ):
        self.embedding_model = load_embedding_model(embedding_model_name)
        self.vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=self.embedding_model,
            persist_directory=chroma_dir,
        )
        self.reranker = CrossEncoder(reranker_model_name, device=device)

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

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        candidates = self.vectorstore.similarity_search_with_relevance_scores(
            query, k=TOP_K_RETRIEVE
        )
        if not candidates:
            return []

        pairs = [(query, doc.page_content) for doc, _ in candidates]
        rerank_scores = self.reranker.predict(pairs)
        ranked = sorted(zip(candidates, rerank_scores), key=lambda x: x[1], reverse=True)

        retrieved = []
        for (doc, _), score in ranked[:top_k]:
            chunk = Chunk(
                chunk_id=doc.metadata.get("block_id", ""),
                doc_id=doc.metadata.get("doc_id", ""),
                text=doc.page_content,
                metadata=doc.metadata,
            )
            retrieved.append(RetrievedChunk(chunk=chunk, score=score))

        return retrieved