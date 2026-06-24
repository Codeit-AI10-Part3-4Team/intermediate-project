def load_embedding_model(name: str):
    if name == "text-embedding-3-small":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model="text-embedding-3-small")
    elif name == "text-embedding-3-large":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model="text-embedding-3-large")
    elif name == "bge-m3":
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name="BAAI/bge-m3",
            model_kwargs={"device": "cuda"},
            encode_kwargs={"normalize_embeddings": True},
        )
    elif name == "ko-sroberta-multitask":
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name="snunlp/KR-SBERT-V40K-klueNLI-augSTS",
            model_kwargs={"device": "cuda"},
            encode_kwargs={"normalize_embeddings": True},
        )
    elif name == "embed-multilingual-v3":
        from langchain_cohere import CohereEmbeddings
        return CohereEmbeddings(model="embed-multilingual-v3.0")
    else:
        raise ValueError(f"알 수 없는 임베딩 모델: {name}")

class Embedder:
    def __init__(self, model_name: str = "bge-m3"):
        self.model_name = model_name
        self.model = load_embedding_model(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.model.embed_documents(texts)