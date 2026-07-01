"""문서 파서 어댑터 — pipeline.py의 파싱 로직을 rag_core Parser 계약에 결속.

pipeline.py는 원래 노트북 이전용 모놀리식 스크립트(CLI + CSV 배치)다. 이 어댑터는
그 단일 파일 파싱 경로(parse_hwp/parse_pdf → 표 정리 → JSON 빌드)를 감싸, 소비자가
Parser Protocol(parse(file_path) -> Document)만으로 쓰게 한다.

설계 노트:
  - 무거운 파싱 의존성(pdfplumber/hwp5/lxml/pandas)은 parse() 안에서 지연 import한다.
    → parsing 패키지를 import한다고 [parsing] extra가 강제되지 않아 코어가 가볍게 유지된다.
  - Document.metadata = pipeline JSON 전체 dict. chunking(chunker.py)이 metadata에서
    sections/qa/metadata/file_name 등을 직접 읽는 기존 소비 계약에 맞춘 것이다.
  - 파싱 실패는 삼키지 않고 명확한 예외로 raise → api 레이어가 HTTP 에러로 변환한다.
"""

from __future__ import annotations

from pathlib import Path

from rag_core.schemas import Document

_SUPPORTED_FORMATS = ("hwp", "pdf")


class ParsingError(Exception):
    """문서 파싱 실패(손상된 파일, 추출 결과 없음 등)."""


class UnsupportedFormatError(ParsingError):
    """지원하지 않는 파일 형식."""


class RfpParser:
    """HWP/PDF → Document. pipeline.py 파싱 로직의 얇은 어댑터."""

    #: 큰 섹션 하위분할 플래그 임계치 (pipeline 단일 파일 경로와 동일).
    _LARGE_SECTION_THRESHOLD = 30

    def parse(self, file_path: str) -> Document:
        path = Path(file_path)

        # 저렴한 검증 먼저 — 무거운 파싱 의존성을 import하기 전에 실패시킨다.
        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
        fmt = path.suffix.lstrip(".").lower()
        if fmt not in _SUPPORTED_FORMATS:
            raise UnsupportedFormatError(
                f"지원하지 않는 형식: {fmt!r} (지원: {', '.join(_SUPPORTED_FORMATS)})"
            )

        # 지연 import — pdfplumber/hwp5/lxml/pandas 등 [parsing] extra는 여기서만 필요.
        from . import pipeline as p

        if fmt == "hwp":
            sections, qa_info = p.parse_hwp(path)
        else:  # pdf
            sections, qa_info = p.parse_pdf(path)

        if qa_info.get("total_sections", 0) == 0:
            reason = (qa_info.get("extraction_warnings") or ["알 수 없는 파싱 실패"])[0]
            raise ParsingError(f"{path.name}: {reason}")

        p.clean_tables_in_doc(sections)
        p.flag_large_sections(sections, threshold=self._LARGE_SECTION_THRESHOLD)

        doc_dict = p.build_json_single(path, sections, qa_info, toc=[])
        text = " ".join(b["content"] for s in sections for b in s["blocks"])

        return Document(
            doc_id=doc_dict["doc_id"],
            source_path=str(path),
            text=text,
            metadata=doc_dict,
        )
