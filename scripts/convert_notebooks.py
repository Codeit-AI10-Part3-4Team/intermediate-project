"""
notebook/ 디렉터리의 *.ipynb 파일을 src/ 디렉터리의 *.py 파일로 변환하는 스크립트입니다.

Usage:
    python scripts/convert_notebooks.py                              # 전체 변환
    python scripts/convert_notebooks.py --notebook {notebook_name}   # 특정 notebook 그룹 변환
    python scripts/convert_notebooks.py --dry-run                    # 변환 결과 확인만
    python scripts/convert_notebooks.py --force                      # 강제 변환 (타임스탬프 무시)
"""

### 실행 예시 ###
# 1. 단일 파일 지정 (확장자 생략)
# python scripts/convert_notebooks.py --notebook eda
#
# 2. 단일 파일 지정 (확장자 포함도 동일하게 동작)
# python scripts/convert_notebooks.py --notebook eda.ipynb
#
# 3. 복수 파일 그룹 지정
#python scripts/convert_notebooks.py --notebook eda pipeline tokenizer
#
# 4. 그룹 + dry-run (실제 변환 없이 대상 확인)
# python scripts/convert_notebooks.py --notebook eda pipeline --dry-run
#
# 5. 그룹 + force (타임스탬프 무시하고 강제 변환)
# python scripts/convert_notebooks.py --notebook tokenizer cleaner --force
#
# 6. 전체 변환 (--notebook 미지정)
# python scripts/convert_notebooks.py

import argparse
import logging
import re
import sys
from enum import IntEnum
from pathlib import Path

import nbformat
from nbconvert import PythonExporter

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK_DIR = PROJECT_ROOT / "notebooks"
OUTPUT_DIR = PROJECT_ROOT / "src/rag_core"

EXCLUDE_PATTERNS = ["checkpoint", ".ipynb_checkpoints"]

_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_MAGIC_PATTERN = re.compile(r"^\s*[%!].+$", re.MULTILINE)


class ExitCode(IntEnum):
    SUCCESS = 0         # 모든 변환 성공 (건너뜀 포함)
    PARTIAL_FAILURE = 1 # 일부 변환 실패
    NO_TARGETS = 2      # 변환 대상 없음
    INVALID_INPUT = 3   # 존재하지 않는 notebook 지정


def _strip_ansi(text: str) -> str:
    """ANSI escape sequence를 제거합니다."""
    return _ANSI_ESCAPE.sub("", text)


def _strip_magic_commands(source: str) -> str:
    """IPython 매직 커맨드와 셸 커맨드를 제거합니다."""
    cleaned = _MAGIC_PATTERN.sub("", source)
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def _is_excluded(path: Path) -> bool:
    return any(pattern in str(path) for pattern in EXCLUDE_PATTERNS)


def _needs_update(nb_path: Path, py_path: Path) -> bool:
    """소스 notebook이 더 최신이면 True."""
    if not py_path.exists():
        return True
    return nb_path.stat().st_mtime > py_path.stat().st_mtime


def collect_notebooks(
    notebook_dir: Path,
    targets: list[str] | None = None,
) -> list[Path]:
    """
    변환 대상 .ipynb 파일 목록을 반환합니다.

    Args:
        notebook_dir: 탐색 루트 디렉터리
        targets: 파일명 필터 목록 (확장자 무관, None이면 전체 대상)

    Returns:
        매칭된 Path 목록. targets에 미존재 항목이 있으면 경고 후 제외.
    """
    all_notebooks = [
        p for p in notebook_dir.rglob("*.ipynb")
        if not _is_excluded(p)
    ]

    if not targets:
        return all_notebooks

    target_stems = {Path(t).stem for t in targets}
    matched = [p for p in all_notebooks if p.stem in target_stems]

    unmatched = target_stems - {p.stem for p in matched}
    for stem in sorted(unmatched):
        logger.warning("notebook을 찾을 수 없음: '%s'", stem)

    return matched


def resolve_output_path(nb_path: Path, notebook_dir: Path, output_dir: Path) -> Path:
    """notebook/ 하위 상대 경로를 유지하여 src/ 경로를 생성합니다."""
    return output_dir / nb_path.relative_to(notebook_dir).with_suffix(".py")


def convert_notebook(nb_path: Path, py_path: Path) -> bool:
    """
    단일 .ipynb 파일을 .py 파일로 변환합니다.

    Args:
        nb_path: 변환 대상 notebook 파일 경로
        py_path: 변환 결과를 저장할 .py 파일 경로

    Returns:
        변환 성공 여부
    """
    try:
        nb_path.resolve(strict=True)
        nb = nbformat.read(nb_path, as_version=4)

        exporter = PythonExporter()
        exporter.exclude_input_prompt = True
        exporter.exclude_output_prompt = True
        exporter.exclude_output = True  # 출력 셀 제거 → ANSI 발생 원천 차단

        source, _ = exporter.from_notebook_node(nb)
        source = _strip_ansi(source)
        source = _strip_magic_commands(source)

        py_path.parent.mkdir(parents=True, exist_ok=True)
        py_path.write_text(source, encoding="utf-8")

        logger.info(
            "변환 완료: %s → %s",
            nb_path.relative_to(PROJECT_ROOT),
            py_path.relative_to(PROJECT_ROOT),
        )
        return True

    except FileNotFoundError:
        logger.error("파일 없음: %s", nb_path)
    except nbformat.reader.NotJSONError:
        logger.error("유효하지 않은 notebook 형식: %s", nb_path)
    except PermissionError:
        logger.error("파일 쓰기 권한 없음: %s", py_path)
    except Exception as e:  # noqa: BLE001
        logger.error("변환 실패 [%s]: %s", nb_path.name, e)

    return False


def run(
    *,
    targets: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> ExitCode:
    notebooks = collect_notebooks(NOTEBOOK_DIR, targets)

    if not notebooks:
        logger.warning("변환 대상 notebook이 없습니다: %s", NOTEBOOK_DIR)
        return ExitCode.NO_TARGETS

    # targets 지정 시, 전혀 매칭이 안 된 경우 조기 종료
    if targets and not notebooks:
        return ExitCode.INVALID_INPUT

    success_count = 0
    skip_count = 0
    fail_count = 0

    for nb_path in sorted(notebooks):
        py_path = resolve_output_path(nb_path, NOTEBOOK_DIR, OUTPUT_DIR)

        if not force and not _needs_update(nb_path, py_path):
            logger.debug("변경 없음, 건너뜀: %s", nb_path.name)
            skip_count += 1
            continue

        if dry_run:
            logger.info(
                "[dry-run] %s → %s",
                nb_path.relative_to(PROJECT_ROOT),
                py_path.relative_to(PROJECT_ROOT),
            )
            continue

        if convert_notebook(nb_path, py_path):
            success_count += 1
        else:
            fail_count += 1

    logger.info(
        "결과 — 성공: %d, 실패: %d, 건너뜀: %d",
        success_count,
        fail_count,
        skip_count,
    )
    return ExitCode.PARTIAL_FAILURE if fail_count > 0 else ExitCode.SUCCESS


def main() -> None:
    parser = argparse.ArgumentParser(description="notebook → src .py 변환 스크립트")
    parser.add_argument(
        "--notebook",
        nargs="+",
        metavar="NAME",
        help="변환할 notebook 이름 (확장자 무관, 복수 지정 가능). 미지정 시 전체 변환.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변환 없이 대상 목록만 출력",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="타임스탬프 무시하고 전체 강제 변환",
    )
    args = parser.parse_args()

    sys.exit(run(targets=args.notebook, dry_run=args.dry_run, force=args.force))


if __name__ == "__main__":
    main()