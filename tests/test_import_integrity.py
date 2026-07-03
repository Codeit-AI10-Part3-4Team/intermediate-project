# tests/test_import_integrity.py
"""내부 모듈 import 무결성 테스트 (정적 검사 — 의존성 설치 불필요).

src/ 아래 모든 파이썬 파일의 `rag_core.*` / `api.*` import가 실제로 존재하는
모듈 파일을 가리키는지 AST로 검증한다. 무거운 의존성(torch·langgraph 등)을
import하지 않으므로 CI 기본 설치에서도 항상 돈다.

배경: 존재하지 않는 `rag_core.prompts.prompt`를 import하는 코드가 머지됐지만,
해당 파일이 `# mypy: ignore-errors` 상태였고 테스트도 없어 CI가 잡지 못했다
(use_mock=False 기동이 ModuleNotFoundError로 즉사하는 상태로 main에 존재).
이 테스트는 그런 깨진 내부 import를 정적으로 차단한다.

업데이트: rag_core.prompts.prompt는 하위 호환용 shim 모듈로 커밋되어
더 이상 KNOWN_MISSING에 있을 필요가 없다 (exaone_rag_qa_prompt /
exaone_multi_doc_prompt를 builder.py가 쓰는 템플릿 파일에서 다시 export).
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
INTERNAL_TOP_PACKAGES = {"rag_core", "api"}

# 이미 main에 존재하는 깨진 import를 여기 추적한다 (현재는 없음).
KNOWN_MISSING: set[str] = set()


def _iter_internal_imports(tree: ast.AST):
    """모듈 내 rag_core/api import 문의 (모듈 경로, 라인) 나열."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in INTERNAL_TOP_PACKAGES:
                    yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            # 상대 import(level>0)는 파일 위치 의존이라 여기선 절대 import만 본다.
            if node.level == 0 and node.module:
                if node.module.split(".")[0] in INTERNAL_TOP_PACKAGES:
                    yield node.module, node.lineno


def _module_exists(module: str) -> bool:
    rel = Path(*module.split("."))
    return (SRC / rel).with_suffix(".py").exists() or (SRC / rel / "__init__.py").exists()


def test_internal_imports_resolve():
    broken: list[str] = []
    for py_file in sorted(SRC.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for module, lineno in _iter_internal_imports(tree):
            if not _module_exists(module) and module not in KNOWN_MISSING:
                rel = py_file.relative_to(SRC.parent)
                broken.append(f"{rel}:{lineno} → '{module}' 모듈이 src/에 존재하지 않습니다")

    assert not broken, "깨진 내부 import 발견:\n" + "\n".join(broken)


def test_known_missing_list_is_current():
    # 허용목록의 모듈이 커밋되면 목록에서 제거하도록 강제한다 (목록 부패 방지).
    stale = [m for m in KNOWN_MISSING if _module_exists(m)]
    assert not stale, (
        f"이제 존재하는 모듈이 KNOWN_MISSING에 남아 있습니다 — 목록에서 제거하세요: {stale}"
    )