"""src/rag_core/prompts/prompt.py

하위 호환용 shim 모듈입니다.

원래 이 파일에는 `exaone_rag_qa_prompt`, `exaone_multi_doc_prompt`라는 이름으로
완성된 프롬프트 템플릿 문자열을 직접 정의해서 다른 모듈(LangGraph 라우터 등)이
바로 import해서 쓰도록 되어 있었습니다. 이후 프롬프트 템플릿을 `.txt` 파일로
분리하고 `builder.py`의 `build_prompt()` 함수로 조립하는 방식으로 리팩토링하면서,
이 파일 자체가 삭제되어 `from rag_core.prompts.prompt import exaone_rag_qa_prompt, ...`
구문이 ModuleNotFoundError를 일으키는 문제가 있었습니다
(APP_USE_MOCK=false로 실행 시 lifespan에서 즉시 실패 → 서비스 기동 불가).

이 shim은 builder.py가 실제로 읽는 templates/ 폴더의 원본 텍스트를 그대로
예전 이름으로 다시 내보내서, 이 이름을 참조하는 기존 코드를 한 줄도 고치지
않고도 계속 동작하게 합니다. 템플릿 내용은 builder.py와 항상 같은 파일을
가리키므로, 향후 프롬프트 규칙이 수정되면 이 shim도 자동으로 최신 내용을
반영합니다(별도로 두 곳을 동기화할 필요가 없습니다).

신규 코드는 이 이름 대신 `rag_core.prompts.builder.build_prompt()`를
직접 사용하는 것을 권장합니다 — doc_list(build_doc_metadata_table()로 생성)까지
포함해서 조립해주는 정식 인터페이스입니다.

주의: 아래 문자열은 `{question}`, `{context}`, `{doc_list}` 자리표시자가
채워지지 않은 원본 템플릿입니다. 예전 코드가 `.format(question=..., context=...)`처럼
doc_list 없이 호출하고 있었다면, 템플릿에 `{doc_list}` 자리표시자가 있어
KeyError가 날 수 있습니다 — 이 경우 호출부에 doc_list 인자를 추가해야 합니다
(build_doc_metadata_table()로 생성 가능).
"""

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(name: str) -> str:
    with open(_TEMPLATES_DIR / name, encoding="utf-8") as f:
        return f.read()


exaone_rag_qa_prompt = _load_template("prompt_template_v1.txt")
exaone_multi_doc_prompt = _load_template("prompt_template_multi_v1.txt")
