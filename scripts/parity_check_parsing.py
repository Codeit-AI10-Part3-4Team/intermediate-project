#!/usr/bin/env python3
"""파서 parity 검증 — 원본 ipynb 골든 JSON ↔ py 파이프라인 산출 JSON 비교.

ipynb→py 전환(src/rag_core/parsing/pipeline.py)이 파싱 결과를 바꾸지 않았는지
검증한다. 레이어드 비교로, 가장 결정적인 곳에서 회귀를 잡는다:

  1) dedup_hash  : qa.dedup_hash = sha256(전체 블록 텍스트). 텍스트 결정적 동등성.
  2) 구조        : sections/blocks 개수 + 첫 불일치 블록(type/content) 위치.
  3) parse_method: 추출 경로 변화(A1→B 폴백 등)는 출력이 달라졌을 강한 신호.

임베딩 비교는 여기서 하지 않는다(Phase 2). dedup_hash가 일치하면 텍스트가
바이트 동일이므로 임베딩도 tolerance 내에서 동일하다 — 따라서 GPU가 필요 없다.

사용법:
  python scripts/parity_check_parsing.py --golden ./golden/docs --candidate ./new/docs
  python scripts/parity_check_parsing.py --golden ... --candidate ... --verbose

종료 코드: parity 실패(불일치/누락)가 하나라도 있으면 1, 모두 일치하면 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 비교는 allowlist 방식(아래 diff_doc에서 특정 qa 필드만 비교)이라,
# processed_at 같은 실행마다 달라지는 휘발성 필드는 자연히 제외된다.


def load_docs(docs_dir: Path) -> dict[str, dict[str, Any]]:
    """디렉토리의 {doc_id}.json들을 doc_id→문서 dict로 적재."""
    if not docs_dir.is_dir():
        raise NotADirectoryError(f"디렉토리가 아닙니다: {docs_dir}")

    docs: dict[str, dict[str, Any]] = {}
    for path in sorted(docs_dir.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise ValueError(f"JSON 적재 실패: {path} ({e})") from e
        doc_id = doc.get("doc_id", path.stem)
        docs[doc_id] = doc
    return docs


def _flatten_blocks(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """문서의 모든 블록을 순서대로 (type, content) 리스트로 평탄화."""
    blocks: list[tuple[str, str]] = []
    for section in doc.get("sections", []):
        for blk in section.get("blocks", []):
            blocks.append((blk.get("type", ""), blk.get("content", "")))
    return blocks


def _first_block_mismatch(golden: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    """첫 번째로 어긋나는 블록의 위치/유형을 사람이 읽을 수 있게 반환."""
    g_blocks = _flatten_blocks(golden)
    c_blocks = _flatten_blocks(candidate)
    for i, (g, c) in enumerate(zip(g_blocks, c_blocks)):
        if g != c:
            g_type, g_text = g
            c_type, c_text = c
            if g_type != c_type:
                return f"블록#{i}: type {g_type}→{c_type}"
            return (
                f"블록#{i}({g_type}): content 다름 "
                f"(golden {len(g_text)}자 vs candidate {len(c_text)}자)"
            )
    if len(g_blocks) != len(c_blocks):
        return f"블록 개수 다름: {len(g_blocks)}→{len(c_blocks)}"
    return None


@dataclass
class DocDiff:
    """단일 문서의 parity 비교 결과."""

    doc_id: str
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons


def diff_doc(golden: dict[str, Any], candidate: dict[str, Any]) -> DocDiff:
    """골든/후보 문서 한 쌍을 레이어드로 비교 (순수 함수)."""
    doc_id = golden.get("doc_id", "?")
    diff = DocDiff(doc_id=doc_id)

    g_qa = golden.get("qa", {})
    c_qa = candidate.get("qa", {})

    # 1) 텍스트 결정적 동등성 — 가장 결정적인 신호.
    g_hash = g_qa.get("dedup_hash")
    c_hash = c_qa.get("dedup_hash")
    if g_hash != c_hash:
        diff.reasons.append(f"dedup_hash 불일치 ({g_hash} → {c_hash})")
        loc = _first_block_mismatch(golden, candidate)
        if loc:
            diff.reasons.append(f"  ↳ 첫 불일치 {loc}")

    # 2) 구조 — 섹션/블록/표 개수.
    for field_name in ("total_sections", "total_blocks", "table_blocks"):
        g_val, c_val = g_qa.get(field_name), c_qa.get(field_name)
        if g_val != c_val:
            diff.reasons.append(f"{field_name}: {g_val} → {c_val}")

    # 3) 추출 경로 변화 — 폴백 전환은 출력이 달라졌을 강한 신호.
    g_method, c_method = g_qa.get("parse_method"), c_qa.get("parse_method")
    if g_method != c_method:
        diff.reasons.append(f"parse_method: {g_method} → {c_method}")

    return diff


def compare_dirs(
    golden_dir: Path, candidate_dir: Path
) -> tuple[list[DocDiff], list[str], list[str]]:
    """두 디렉토리를 비교 → (불일치 목록, golden 전용 doc_id, candidate 전용 doc_id)."""
    golden = load_docs(golden_dir)
    candidate = load_docs(candidate_dir)

    common = sorted(set(golden) & set(candidate))
    golden_only = sorted(set(golden) - set(candidate))
    candidate_only = sorted(set(candidate) - set(golden))

    diffs = [diff_doc(golden[d], candidate[d]) for d in common]
    return diffs, golden_only, candidate_only


def main() -> int:
    ap = argparse.ArgumentParser(description="파서 parity 검증 (골든 JSON ↔ py 산출 JSON)")
    ap.add_argument("--golden", required=True, type=Path, help="원본 ipynb 산출 JSON 디렉토리")
    ap.add_argument(
        "--candidate", required=True, type=Path, help="py 파이프라인 산출 JSON 디렉토리"
    )
    ap.add_argument("--verbose", action="store_true", help="일치 문서도 모두 출력")
    args = ap.parse_args()

    try:
        diffs, golden_only, candidate_only = compare_dirs(args.golden, args.candidate)
    except (NotADirectoryError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2

    failures = [d for d in diffs if not d.ok]
    passed = len(diffs) - len(failures)

    print("=== 파서 parity 결과 ===")
    print(
        f"공통 {len(diffs)}건 | 일치 {passed} / 불일치 {len(failures)} | "
        f"golden 전용 {len(golden_only)} | candidate 전용 {len(candidate_only)}"
    )

    if golden_only:
        print(f"\n[누락] candidate에 없는 문서: {', '.join(golden_only)}")
    if candidate_only:
        print(f"[추가] golden에 없는 문서: {', '.join(candidate_only)}")

    if failures:
        print("\n--- 불일치 상세 ---")
        for d in failures:
            print(f"✗ {d.doc_id}")
            for reason in d.reasons:
                print(f"    {reason}")

    if args.verbose:
        print("\n--- 일치 문서 ---")
        for d in diffs:
            if d.ok:
                print(f"✓ {d.doc_id}")

    has_failure = bool(failures or golden_only or candidate_only)
    print("\n결과:", "실패(차이 있음)" if has_failure else "통과(완전 일치)")
    return 1 if has_failure else 0


if __name__ == "__main__":
    sys.exit(main())
