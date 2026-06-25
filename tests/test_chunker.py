import json
from rag_core.schemas import Document
from rag_core.chunking.chunker import Chunker

with open('data/parsed_json/D001.json', encoding='utf-8') as f:
    raw = json.load(f)

doc = Document(doc_id=raw['doc_id'], source_path='', text='', metadata=raw)
chunker = Chunker()
chunks = chunker.chunk(doc)
print(f'청크 수: {len(chunks)}')
print(chunks[0].text[:200])
