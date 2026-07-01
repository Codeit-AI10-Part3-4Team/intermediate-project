"""
src/rag_core/prompts/builder.py

templates/ 폴더의 프롬프트 템플릿을 읽어서
검색 결과(context)와 사용자 질의를 조합하여
LLM에 전달할 최종 프롬프트 문자열을 구성합니다.

담당: 지우님 (Generation 트랙)
"""

import os
from pathlib import Path

# 템플릿 파일 경로
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_TEMPLATE_SINGLE = _TEMPLATES_DIR / "prompt_template_v1.txt"
_TEMPLATE_MULTI = _TEMPLATES_DIR / "prompt_template_multi_v1.txt"

# 모델명 환경 변수로 주입 (기본값: exaone3.5:7.8b)
TARGET_MODEL = os.environ.get("OLLAMA_MODEL", "exaone3.5:7.8b")


def _load_template(path: Path) -> str:
    """템플릿 파일을 읽어서 문자열로 반환합니다."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_prompt(question: str, context: str, doc_list: str, is_multi_doc: bool = False) -> str:
    """
    템플릿 파일을 읽어서 context, doc_list, question을 채워 반환합니다.

    Args:
        question: 사용자 질의
        context: format_rag_context()가 반환한 문서 내용 문자열
        doc_list: build_doc_metadata_table()이 반환한 문서 목록 문자열
        is_multi_doc: 다중문서 질문 여부

    Returns:
        LLM에 전달할 최종 프롬프트 문자열
    """
    template_path = _TEMPLATE_MULTI if is_multi_doc else _TEMPLATE_SINGLE
    template = _load_template(template_path)
    return template.format(
        question=question,
        context=context,
        doc_list=doc_list,
    )
