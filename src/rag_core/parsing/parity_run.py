#!/usr/bin/env python3
"""파서 parity 원클릭 래퍼 — candidate 생성 + parity 비교 + 환경 기록.

기존 노트북 파서가 만든 산출(golden)과, 이 저장소의 py 파서
(src/rag_core/parsing/pipeline.py)를 "같은 원본 파일"에 돌린 산출(candidate)을
한 번에 만들고 비교한다. 환경 차이로 인한 오탐(코드가 아니라 라이브러리 버전
때문에 텍스트가 달라지는 경우)을 구분할 수 있게 파싱 라이브러리·soffice 버전도
함께 기록한다.

이 스크립트는 저장소에 커밋하지 않는다(개별 전달용).

전제(모두 golden을 만든 그 자산이어야 함):
  - 원본 HWP/PDF 폴더
  - data_list.csv (파서용 메타 CSV, 12열 — eval golden_dataset_v2.csv 아님)
  - 노트북 golden docs/ 폴더 ({doc_id}.json 들)

사용법:
  python parity_run.py \
    --repo   /path/to/intermediate-project \
    --files-dir "/path/원본문서" \
    --csv       "/path/data_list.csv" \
    --golden    "/path/Preprocessed dataset/docs" \
    --out       ./parity_out \
    [--doc-ids D001 D002] [--verbose]

종료 코드: parity 통과(완전 일치) 0 / 불일치·누락 1 / 실행 오류 2.
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# golden 생성 시점과 맞춰야 하는(=출력에 영향을 주는) 파싱 라이브러리들.
_PARSING_PKGS = ("pyhwp", "pdfplumber", "lxml", "pandas", "python-docx")


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "(미설치)"


def _soffice_version() -> str:
    for exe in ("soffice", "libreoffice"):
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, timeout=15)
            if r.returncode == 0:
                return r.stdout.decode(errors="replace").strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            continue
    return "(soffice 없음 — HWP LibreOffice 폴백 불가)"


def write_env_report(out_dir: Path) -> Path:
    """파싱 환경 스냅샷을 기록 — parity 오탐 원인 추적용."""
    lines = [
        "# parity 실행 환경 스냅샷",
        f"python           : {platform.python_version()} ({sys.executable})",
        f"platform         : {platform.platform()}",
        "",
        "# 파싱 라이브러리 버전 (golden 생성 시점과 달라지면 parity가 깨질 수 있음)",
    ]
    lines += [f"{name:16s} : {_pkg_version(name)}" for name in _PARSING_PKGS]
    lines += ["", f"soffice          : {_soffice_version()}", ""]
    report = out_dir / "parity_env.txt"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def run_pipeline(
    pipeline_py: Path, files_dir: Path, csv: Path, out_dir: Path, doc_ids: list[str] | None
) -> int:
    """py 파서를 원본에 돌려 candidate({out}/docs/*.json)를 생성."""
    cmd = [
        sys.executable,
        str(pipeline_py),
        "--files_dir",
        str(files_dir),
        "--csv_path",
        str(csv),
        "--output_dir",
        str(out_dir),
    ]
    if doc_ids:
        cmd += ["--doc_ids", *doc_ids]
    print(f"\n[1/2] candidate 생성 → {out_dir / 'docs'}")
    print("      $ " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def run_parity(parity_py: Path, golden: Path, candidate: Path, verbose: bool) -> int:
    """golden(노트북) vs candidate(py) 비교."""
    cmd = [
        sys.executable,
        str(parity_py),
        "--golden",
        str(golden),
        "--candidate",
        str(candidate),
    ]
    if verbose:
        cmd.append("--verbose")
    print("\n[2/2] parity 비교 (golden ↔ candidate)")
    print("      $ " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="파서 parity 원클릭 래퍼")
    ap.add_argument("--repo", required=True, type=Path, help="intermediate-project 저장소 루트")
    ap.add_argument("--files-dir", required=True, type=Path, help="원본 HWP/PDF 폴더")
    ap.add_argument("--csv", required=True, type=Path, help="파서용 메타 CSV (data_list.csv)")
    ap.add_argument("--golden", required=True, type=Path, help="노트북 golden docs/ 폴더")
    ap.add_argument("--out", required=True, type=Path, help="candidate 출력 루트 (하위에 docs/ 생성)")
    ap.add_argument("--doc-ids", nargs="*", default=None, help="일부만 처리 (예: D001 D002)")
    ap.add_argument("--verbose", action="store_true", help="parity 일치 문서도 모두 출력")
    args = ap.parse_args()

    pipeline_py = args.repo / "pipeline.py"
    parity_py = args.repo / "scripts" / "parity_check_parsing.py"

    # 사전 점검 — 없으면 조기 종료(원인 명확화).
    missing = [
        f"{label}: {p}"
        for label, p in [
            ("파서 스크립트", pipeline_py),
            ("parity 스크립트", parity_py),
            ("원본 폴더", args.files_dir),
            ("메타 CSV", args.csv),
            ("golden docs/", args.golden),
        ]
        if not p.exists()
    ]
    if missing:
        print("오류: 다음 경로를 찾을 수 없습니다:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    env_report = write_env_report(args.out)
    print(f"환경 스냅샷 기록: {env_report}")

    rc = run_pipeline(pipeline_py, args.files_dir, args.csv, args.out, args.doc_ids)
    if rc != 0:
        print(f"\n오류: candidate 생성 실패 (pipeline.py exit={rc})", file=sys.stderr)
        return 2

    candidate = args.out / "docs"
    produced = sorted(candidate.glob("*.json")) if candidate.is_dir() else []
    if not produced:
        print(f"\n오류: candidate 산출물 없음: {candidate}", file=sys.stderr)
        return 2
    print(f"      candidate {len(produced)}건 생성됨")

    parity_rc = run_parity(parity_py, args.golden, candidate, args.verbose)

    print("\n" + "=" * 50)
    if parity_rc == 0:
        print("최종: ✅ parity 통과 — 노트북 파서와 py 파서 산출이 완전 일치")
    else:
        print("최종: ❌ parity 불일치 — 위 상세 확인")
        print(f"      환경 차이 가능성부터 점검: {env_report}")
    print("=" * 50)
    return parity_rc


if __name__ == "__main__":
    sys.exit(main())
