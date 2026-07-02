#!/usr/bin/env python3
"""파서 parity 검증 — 원본 ipynb 골든 JSON ↔ py 파이프라인 산출 JSON 비교.

ipynb→py 전환(src/rag_core/parsing/pipeline.py)이 파싱 결과를 바꾸지 않았는지
검증한다. 레이어드 비교로, 가장 결정적인 곳에서 회귀를 잡는다:

  1) 본문 텍스트  : 저장된 블록에서 sha256을 재계산해 비교(전체 블록 텍스트).
                   저장된 qa.dedup_hash는 파이프라인마다 계산 "시점"이 달라(예: 표
                   정리 전/후) 텍스트가 같아도 어긋날 수 있어 신뢰하지 않는다.
  2) 구조        : 저장 블록에서 재계산한 sections/blocks/표 개수 + 첫 불일치 블록 위치.
  3) parse_method: 추출 경로 변화(A1→B 폴백 등). 이름만 다른 동등 라벨은 정규화 후 비교.

임베딩 비교는 여기서 하지 않는다(Phase 2). 본문 텍스트가 일치하면 바이트 동일이므로
임베딩도 tolerance 내에서 동일하다 — 따라서 GPU가 필요 없다.

사용법:
  python scripts/parity_check_parsing.py --golden ./golden/docs --candidate ./new/docs
  python scripts/parity_check_parsing.py --golden ... --candidate ... --verbose
  python scripts/parity_check_parsing.py --golden ... --candidate ... --full  # 상이 블록 전체

종료 코드: parity 실패(불일치/누락)가 하나라도 있으면 1, 모두 일치하면 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 비교는 저장 블록에서 재계산한 본문/구조 + parse_method만 본다.
# processed_at·metadata·toc 등 나머지 필드는 비교 대상이 아니다.

# 노트북↔py 이전 과정에서 이름만 바뀐, 동일 추출 경로의 라벨 별칭.
# (예: 노트북 "hwp5xml" ≡ py "A1_inprocess_api" — 둘 다 hwp5 XML in-process 경로)
_PARSE_METHOD_ALIASES = {
    "hwp5xml": "A1_inprocess_api",
}


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


def _normalize_parse_method(method: str | None) -> str | None:
    """이름만 다른 동등 추출 경로를 하나로 정규화 (폴백 전환 같은 실질 변화는 보존)."""
    return _PARSE_METHOD_ALIASES.get(method, method) if method is not None else None


def _canonical_text(doc: dict[str, Any]) -> str:
    """저장된 블록에서 본문 텍스트를 재구성 (build_json의 all_text와 동일 규칙)."""
    return " ".join(content for _type, content in _flatten_blocks(doc))


def _canonical_hash(doc: dict[str, Any]) -> str:
    """저장 블록 기준으로 재계산한 본문 해시 — 저장된 qa.dedup_hash에 의존하지 않는다."""
    return hashlib.sha256(_canonical_text(doc).encode()).hexdigest()


def _structure_counts(doc: dict[str, Any]) -> tuple[int, int, int]:
    """저장된 구조에서 (섹션 수, 블록 수, 표 블록 수)를 재계산."""
    blocks = _flatten_blocks(doc)
    total_blocks = len(blocks)
    table_blocks = sum(1 for btype, _content in blocks if btype == "table")
    total_sections = len(doc.get("sections", []))
    return total_sections, total_blocks, table_blocks


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


def _all_block_mismatches(golden: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """어긋나는 "모든" 블록을 열거 (첫 하나만 보는 _first_block_mismatch와 달리 전체)."""
    g_blocks = _flatten_blocks(golden)
    c_blocks = _flatten_blocks(candidate)
    out: list[str] = []
    for i, (g, c) in enumerate(zip(g_blocks, c_blocks)):
        if g == c:
            continue
        if g[0] != c[0]:
            out.append(f"블록#{i}: type {g[0]}→{c[0]}")
        else:
            out.append(f"블록#{i}({g[0]}): {len(g[1])}자 vs {len(c[1])}자")
    if len(g_blocks) != len(c_blocks):
        out.append(f"블록 개수: {len(g_blocks)} → {len(c_blocks)}")
    return out


def _table_mismatch_count(mismatches: list[str]) -> int:
    return sum(1 for m in mismatches if "(table)" in m or "table→" in m or "→table" in m)


@dataclass
class DocDiff:
    """단일 문서의 parity 비교 결과."""

    doc_id: str
    reasons: list[str] = field(default_factory=list)
    # 본문 텍스트가 어긋난 경우 "모든" 상이 블록 상세(--full 출력용). ok 판정엔 영향 없음.
    block_mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons


def diff_doc(golden: dict[str, Any], candidate: dict[str, Any]) -> DocDiff:
    """골든/후보 문서 한 쌍을 레이어드로 비교 (순수 함수).

    저장된 qa.dedup_hash/카운트는 파이프라인마다 계산 시점이 달라 신뢰할 수 없으므로,
    본문 해시와 구조 카운트를 **저장된 블록에서 재계산**해 비교한다.
    """
    doc_id = golden.get("doc_id", "?")
    diff = DocDiff(doc_id=doc_id)

    # 1) 본문 텍스트 결정적 동등성 — 저장 블록에서 해시 재계산.
    if _canonical_hash(golden) != _canonical_hash(candidate):
        diff.reasons.append("본문 텍스트 불일치")
        loc = _first_block_mismatch(golden, candidate)
        if loc:
            diff.reasons.append(f"  ↳ 첫 불일치 {loc}")
        # 첫 하나만이 아니라 전체 상이 범위를 함께 보고(표가 여러 개 틀어졌는지 판단용).
        diff.block_mismatches = _all_block_mismatches(golden, candidate)
        n_table = _table_mismatch_count(diff.block_mismatches)
        diff.reasons.append(
            f"  ↳ 상이 블록 총 {len(diff.block_mismatches)}개 (표 {n_table}개) — 전체 목록은 --full"
        )

    # 2) 구조 — 저장 블록에서 재계산한 섹션/블록/표 개수.
    counts = zip(
        ("total_sections", "total_blocks", "table_blocks"),
        _structure_counts(golden),
        _structure_counts(candidate),
    )
    for field_name, g_val, c_val in counts:
        if g_val != c_val:
            diff.reasons.append(f"{field_name}: {g_val} → {c_val}")

    # 3) 추출 경로 변화 — 이름만 다른 동등 라벨은 정규화 후 비교(폴백 전환만 잡는다).
    g_method = golden.get("qa", {}).get("parse_method")
    c_method = candidate.get("qa", {}).get("parse_method")
    if _normalize_parse_method(g_method) != _normalize_parse_method(c_method):
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
    ap.add_argument("--full", action="store_true", help="불일치 문서의 상이 블록을 전체 나열")
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
            if args.full and d.block_mismatches:
                print("    [상이 블록 전체]")
                for bm in d.block_mismatches:
                    print(f"      {bm}")

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