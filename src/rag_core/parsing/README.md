# src/rag_core/parsing/

## 역할
PDF/HWP 등 원본 문서 파일에서 텍스트와 구조(섹션, 표, 목록 등)를 추출하는 모듈입니다.

## 담당
유빈님

## 입력/출력
- 입력: 원본 문서 파일 경로 (`data/` 또는 업로드 API로부터 전달)
- 출력: `rag_core.schemas.Document`. `metadata`에 파싱 JSON 전체(sections/qa/메타)를 담아 `chunking/`이 그대로 소비합니다.

## 구조
- `parser.py` — 진입점 `RfpParser`. `Parser` 계약(`parse(file_path) -> Document`) 구현. 무거운 파싱 의존성은 지연 import.
- `pipeline.py` — 실제 추출 로직(HWP: hwp5 API → hwp5txt → LibreOffice 폴백 / PDF: pdfplumber). 노트북에서 이전된 모놀리식. CLI로도 실행 가능(코퍼스 배치 빌드).
- 무거운 의존성(pyhwp·pdfplumber·lxml·pandas·python-docx)은 `[parsing]` extra: `pip install -e ".[parsing]"`.

## 산출물 연계
- 다음 단계인 `chunking/`(희원님)이 `Document.metadata`(파싱 JSON)를 입력으로 받습니다.
- `notebooks/parsing/`에서 검증된 파싱 로직만 이곳에 함수화되어 들어옵니다. ipynb→py 이전 무결성은 `scripts/parity_check_parsing.py`로 검증(docs/파서_parity_검증_보고서.md).

## 코딩 에이전트 참고
- 신규 형식 지원은 `pipeline.py`에 추출 함수를 더하고 `RfpParser.parse`에서 분기하세요. 소비자는 `Parser` 계약(`parse(file_path) -> Document`)만 봅니다.
- 파싱 실패는 삼키지 말고 명확한 예외로 raise합니다: `UnsupportedFormatError`(미지원 형식) / `ParsingError`(추출 실패) — `api/`가 HTTP 에러(415/422)로 변환합니다.
- 청킹/임베딩 로직을 여기에 작성하지 마세요 (`chunking/` 담당 영역).
