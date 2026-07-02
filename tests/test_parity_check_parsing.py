# tests/test_parity_check_parsing.py
# scripts/parity_check_parsing.py 순수 함수 단위 검증.
# 대상 스크립트는 설치 패키지(src/)가 아니라 scripts/ 아래 독립 파일이므로,
# 파일 경로로 직접 로드해 import 한다 (sys.path 오염 없이).
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "parity_check_parsing.py"
_spec = importlib.util.spec_from_file_location("parity_check_parsing", _SCRIPT)
assert _spec and _spec.loader
parity = importlib.util.module_from_spec(_spec)
# @dataclass가 cls.__module__을 sys.modules에서 조회하므로 exec 전에 등록해야 한다.
sys.modules[_spec.name] = parity
_spec.loader.exec_module(parity)


def _doc(
    doc_id: str, blocks: list[tuple[str, str]], *, parse_method: str = "A1_inprocess_api"
) -> dict:
    """parity 비교 함수가 읽는 최소 문서 dict 빌더 (단일 섹션).

    diff_doc은 저장 블록에서 본문 해시·구조를 재계산하므로, qa에는 parse_method만 둔다.
    """
    return {
        "doc_id": doc_id,
        "sections": [{"blocks": [{"type": t, "content": c} for t, c in blocks]}],
        "qa": {"parse_method": parse_method},
    }


def _write_docs(dir_path: Path, docs: list[dict]) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (dir_path / f"{doc['doc_id']}.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
    return dir_path


# ─────────────────────────────────────────────────────────────
# diff_doc — 저장 블록에서 재계산해 비교
# ─────────────────────────────────────────────────────────────


def test_diff_doc_identical_is_ok():
    doc = _doc("D001", [("text", "hello")])
    diff = parity.diff_doc(doc, doc)
    assert diff.ok
    assert diff.reasons == []


def test_diff_doc_text_mismatch_reports_first_block():
    golden = _doc("D001", [("text", "hello")])
    candidate = _doc("D001", [("text", "hallo")])
    diff = parity.diff_doc(golden, candidate)

    assert not diff.ok
    joined = "\n".join(diff.reasons)
    assert "본문 텍스트 불일치" in joined
    # 텍스트가 어긋나면 첫 불일치 블록 위치도 함께 보고한다.
    assert "블록#0" in joined
    assert "content 다름" in joined


def test_diff_doc_ignores_stale_stored_dedup_hash():
    # 블록(본문)은 동일하지만 저장된 qa.dedup_hash만 다른 경우 — 파이프라인 간
    # 해시 계산 시점 차이(D043 시나리오). 재계산 비교이므로 일치로 판정해야 한다.
    golden = _doc("D001", [("text", "abc"), ("table", "grid")])
    candidate = _doc("D001", [("text", "abc"), ("table", "grid")])
    golden["qa"]["dedup_hash"] = "sha256:STALE_DIFFERENT"
    candidate["qa"]["dedup_hash"] = "sha256:something_else"
    diff = parity.diff_doc(golden, candidate)

    assert diff.ok


def test_diff_doc_block_type_change_reported_via_table_count():
    # content가 같고 type만 text→table로 바뀌면 표 블록 수 변화로 잡힌다.
    golden = _doc("D001", [("text", "x")])
    candidate = _doc("D001", [("table", "x")])
    diff = parity.diff_doc(golden, candidate)

    joined = "\n".join(diff.reasons)
    assert "table_blocks: 0 → 1" in joined


def test_diff_doc_enumerates_all_block_mismatches():
    # 첫 하나만이 아니라 상이 블록 "전체"를 block_mismatches에 담고, 총계를 보고해야 한다.
    golden = _doc("D001", [("table", "aa"), ("text", "b"), ("table", "cc")])
    candidate = _doc("D001", [("table", "aaa"), ("text", "b"), ("table", "ccc")])
    diff = parity.diff_doc(golden, candidate)

    # 블록#0, #2 두 표가 어긋남 (블록#1은 동일).
    assert len(diff.block_mismatches) == 2
    assert any("블록#0" in m for m in diff.block_mismatches)
    assert any("블록#2" in m for m in diff.block_mismatches)
    joined = "\n".join(diff.reasons)
    assert "상이 블록 총 2개 (표 2개)" in joined


def test_diff_doc_reports_block_count_diff():
    golden = _doc("D001", [("text", "a")])
    candidate = _doc("D001", [("text", "a"), ("text", "b")])
    diff = parity.diff_doc(golden, candidate)

    joined = "\n".join(diff.reasons)
    assert "total_blocks: 1 → 2" in joined


def test_diff_doc_reports_section_count_diff():
    # 본문은 같고 섹션 경계만 다른 경우 → 섹션 수 차이로 잡힌다.
    golden = {
        "doc_id": "D001",
        "qa": {"parse_method": "A1_inprocess_api"},
        "sections": [{"blocks": [{"type": "text", "content": "a"}]}],
    }
    candidate = {
        "doc_id": "D001",
        "qa": {"parse_method": "A1_inprocess_api"},
        "sections": [{"blocks": [{"type": "text", "content": "a"}]}, {"blocks": []}],
    }
    diff = parity.diff_doc(golden, candidate)

    joined = "\n".join(diff.reasons)
    assert "total_sections: 1 → 2" in joined


def test_diff_doc_reports_parse_method_fallback():
    # 본문·구조는 같고 추출 경로만 폴백 전환 — 회귀의 강한 신호.
    golden = _doc("D001", [("text", "x")], parse_method="A1_inprocess_api")
    candidate = _doc("D001", [("text", "x")], parse_method="B_libreoffice_docx")
    diff = parity.diff_doc(golden, candidate)

    joined = "\n".join(diff.reasons)
    assert "parse_method: A1_inprocess_api → B_libreoffice_docx" in joined


def test_diff_doc_normalizes_equivalent_parse_method():
    # hwp5xml ≡ A1_inprocess_api (라벨만 다른 동일 엔진) — 불일치로 잡지 않는다 (D026 시나리오).
    golden = _doc("D001", [("text", "x")], parse_method="hwp5xml")
    candidate = _doc("D001", [("text", "x")], parse_method="A1_inprocess_api")
    diff = parity.diff_doc(golden, candidate)

    assert diff.ok


# ─────────────────────────────────────────────────────────────
# _first_block_mismatch
# ─────────────────────────────────────────────────────────────


def test_first_block_mismatch_none_when_identical():
    doc = _doc("D001", [("text", "a"), ("text", "b")])
    assert parity._first_block_mismatch(doc, doc) is None


def test_first_block_mismatch_reports_content_length():
    golden = _doc("D001", [("text", "short")])
    candidate = _doc("D001", [("text", "a much longer body")])
    msg = parity._first_block_mismatch(golden, candidate)
    assert msg is not None
    assert "블록#0" in msg
    assert "5자" in msg and "18자" in msg


def test_first_block_mismatch_reports_count_when_prefix_matches():
    # 겹치는 구간은 동일하고 길이만 다를 때 개수 차이를 보고한다.
    golden = _doc("D001", [("text", "a"), ("text", "b")])
    candidate = _doc("D001", [("text", "a")])
    msg = parity._first_block_mismatch(golden, candidate)
    assert msg == "블록 개수 다름: 2→1"


# ─────────────────────────────────────────────────────────────
# load_docs — 적재 및 예외
# ─────────────────────────────────────────────────────────────


def test_load_docs_keys_by_doc_id(tmp_path):
    _write_docs(tmp_path, [_doc("D001", [("text", "x")]), _doc("D002", [("text", "y")])])
    docs = parity.load_docs(tmp_path)
    assert set(docs) == {"D001", "D002"}


def test_load_docs_raises_on_non_directory(tmp_path):
    f = tmp_path / "not_a_dir.json"
    f.write_text("{}", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        parity.load_docs(f)


def test_load_docs_raises_on_invalid_json(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        parity.load_docs(tmp_path)


# ─────────────────────────────────────────────────────────────
# compare_dirs — 공통/전용 분할 + diff 집계
# ─────────────────────────────────────────────────────────────


def test_compare_dirs_partitions_and_diffs(tmp_path):
    golden_dir = _write_docs(
        tmp_path / "golden",
        [_doc("D001", [("text", "x")]), _doc("D002", [("text", "same")])],
    )
    candidate_dir = _write_docs(
        tmp_path / "candidate",
        [_doc("D002", [("text", "changed")]), _doc("D003", [("text", "z")])],
    )

    diffs, golden_only, candidate_only = parity.compare_dirs(golden_dir, candidate_dir)

    assert golden_only == ["D001"]
    assert candidate_only == ["D003"]
    # 공통은 D002 하나이며, 본문 텍스트가 달라 불일치로 잡혀야 한다.
    assert [d.doc_id for d in diffs] == ["D002"]
    assert not diffs[0].ok