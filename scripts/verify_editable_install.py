# scripts/verify_editable_install.py
"""
Editable install 설치 상태 검증 스크립트.
Usage: python scripts/verify_editable_install.py
"""
import sys
import importlib
import subprocess
from pathlib import Path


def check_import(module_name: str) -> tuple[bool, str]:
    """모듈 import 가능 여부 및 실제 경로 반환."""
    try:
        mod = importlib.import_module(module_name)
        location = getattr(mod, "__file__", None) or getattr(mod, "__path__", ["(namespace)"])[0]
        return True, str(location)
    except ImportError as e:
        return False, str(e)


def check_editable_marker() -> tuple[bool, str]:
    """
    pip show -f 로 .pth 또는 __editable__ 마커 파일 존재 확인.
    editable install은 반드시 site-packages에 심볼릭 링크 또는 .pth 파일을 생성함.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", "-f", "intermediate-project"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, "패키지가 설치되지 않았습니다."

    output = result.stdout
    is_editable = (
        "__editable__" in output
        or ".pth" in output
        or "direct_url.json" in output
    )
    return is_editable, output


def check_live_edit() -> tuple[bool, str]:
    """
    소스 파일 수정이 재설치 없이 반영되는지 확인.
    editable install의 핵심 특성.
    """
    sentinel_path = Path("src/rag_core/__init__.py")
    original_content = sentinel_path.read_text(encoding="utf-8")

    # 임시 심볼 삽입
    sentinel_attr = "_EDITABLE_INSTALL_VERIFIED"
    sentinel_line = f'\n{sentinel_attr} = True  # temporary sentinel\n'
    sentinel_path.write_text(original_content + sentinel_line, encoding="utf-8")

    try:
        import importlib
        import rag_core
        importlib.reload(rag_core)
        success = getattr(rag_core, sentinel_attr, False)
        return success, "라이브 편집 반영 확인" if success else "라이브 편집 미반영 (editable 아님)"
    except Exception as e:
        return False, str(e)
    finally:
        # 원본 복원
        sentinel_path.write_text(original_content, encoding="utf-8")


def main() -> int:
    print(f"Python: {sys.executable}")
    print(f"Version: {sys.version}\n")

    exit_code = 0

    # 1. 패키지 import 확인
    targets = ["rag_core", "rag_core.chunking", "rag_core.embedding", "rag_core.retrieval", "api"]
    print("=== Import 검증 ===")
    for target in targets:
        ok, location = check_import(target)
        status = "✓" if ok else "✗"
        print(f"  {status} {target}")
        print(f"      → {location}")
        if not ok:
            exit_code = 1

    # 2. Editable 마커 확인
    print("\n=== Editable Install 마커 확인 ===")
    ok, detail = check_editable_marker()
    status = "✓" if ok else "✗"
    print(f"  {status} editable 마커 {'존재' if ok else '없음'}")
    if not ok:
        print(f"      → {detail}")
        exit_code = 1

    # 3. 라이브 편집 반영 확인
    print("\n=== 라이브 편집 반영 확인 ===")
    ok, message = check_live_edit()
    status = "✓" if ok else "✗"
    print(f"  {status} {message}")
    if not ok:
        exit_code = 1

    print("\n" + ("✓ 모든 검증 통과" if exit_code == 0 else "✗ 일부 검증 실패"))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())