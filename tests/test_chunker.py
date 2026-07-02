# tests/test_chunker.py
import json
from pathlib import Path

import pytest

from rag_core.chunking.chunker import Chunker
from rag_core.schemas import Document

SAMPLE = Path("data/parsed_json/D001.json")


@pytest.mark.skipif(not SAMPLE.exists(), reason="샘플 데이터(data/parsed_json/D001.json)가 없음")
def test_chunker_on_sample():
    raw = json.loads(SAMPLE.read_text(encoding="utf-8"))
    doc = Document(doc_id=raw["doc_id"], source_path="", text="", metadata=raw)

    chunks = Chunker().chunk(doc)

    assert len(chunks) > 0
    assert chunks[0].text
