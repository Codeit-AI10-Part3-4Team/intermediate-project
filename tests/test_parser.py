# tests/test_parser.py
# RfpParser 어댑터의 Parser 계약 준수 + 예외 경로 검증.
# 실제 HWP/PDF 파싱은 샘플이 있을 때만(skipif) 돌린다 — 무거운 의존성/데이터 불필요.
from pathlib import Path

import pytest

from rag_core.interfaces import Parser
from rag_core.parsing import ParsingError, RfpParser, UnsupportedFormatError

# data/ 아래 아무 HWP/PDF 샘플 (있으면 실제 파싱까지 검증).
_SAMPLES = sorted(Path("data").glob("**/*.hwp")) + sorted(Path("data").glob("**/*.pdf"))


def test_conforms_to_parser_protocol():
    # runtime_checkable Protocol — parse() 시그니처만 맞으면 통과.
    assert isinstance(RfpParser(), Parser)


def test_unsupported_format_error_is_parsing_error():
    assert issubclass(UnsupportedFormatError, ParsingError)


def test_unsupported_format_raises(tmp_path):
    # 존재하지만 지원하지 않는 확장자 → 무거운 파싱 import 이전에 실패해야 한다.
    f = tmp_path / "note.txt"
    f.write_text("hello", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        RfpParser().parse(str(f))


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        RfpParser().parse(str(tmp_path / "nope.hwp"))


@pytest.mark.skipif(not _SAMPLES, reason="data/ 아래 HWP/PDF 샘플이 없음")
def test_parse_sample_returns_document():
    doc = RfpParser().parse(str(_SAMPLES[0]))

    assert doc.doc_id
    assert doc.source_path == str(_SAMPLES[0])
    # chunking 소비 계약: metadata = pipeline JSON 전체 (sections/qa 포함).
    assert doc.metadata.get("sections")
    assert "qa" in doc.metadata
    assert doc.text
