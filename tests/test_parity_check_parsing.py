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
    doc_id: str,
    blocks: list[tuple[str, str]],
    *,
    dedup_hash: str = "sha256:abc",
    total_sections: int = 1,
    total_blocks: int | None = None,
    table_blocks: int = 0,
    parse_method: str = "A1_inprocess_api",
) -> dict:
    """parity 비교 함수가 읽는 최소 문서 dict 빌더."""
    return {
        "doc_id": doc_id,
        "sections": [{"blocks": [{"type": t, "content": c} for t, c in blocks]}],
        "qa": {
            "dedup_hash": dedup_hash,
            "total_sections": total_sections,
            "total_blocks": len(blocks) if total_blocks is None else total_blocks,
            "table_blocks": table_blocks,
            "parse_method": parse_method,
        },
    }


def _write_docs(dir_path: Path, docs: list[dict]) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (dir_path / f"{doc['doc_id']}.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
    return dir_path


# ─────────────────────────────────────────────────────────────
# diff_doc — 레이어드 비교
# ─────────────────────────────────────────────────────────────


def test_diff_doc_identical_is_ok():
    doc = _doc("D001", [("text", "hello")])
    diff = parity.diff_doc(doc, doc)
    assert diff.ok
    assert diff.reasons == []


def test_diff_doc_dedup_hash_mismatch_reports_first_block():
    golden = _doc("D001", [("text", "hello")], dedup_hash="sha256:aaa")
    candidate = _doc("D001", [("text", "hallo")], dedup_hash="sha256:bbb")
    diff = parity.diff_doc(golden, candidate)

    assert not diff.ok
    joined = "\n".join(diff.reasons)
    assert "dedup_hash 불일치" in joined
    # 텍스트가 어긋나면 첫 불일치 블록 위치도 함께 보고한다.
    assert "블록#0" in joined
    assert "content 다름" in joined


def test_diff_doc_reports_block_type_change():
    golden = _doc("D001", [("text", "x")], dedup_hash="sha256:aaa")
    candidate = _doc("D001", [("table", "x")], dedup_hash="sha256:bbb")
    diff = parity.diff_doc(golden, candidate)

    joined = "\n".join(diff.reasons)
    assert "type text→table" in joined


def test_diff_doc_reports_structure_count_diffs():
    golden = _doc("D001", [("text", "x")], total_sections=1, total_blocks=1, table_blocks=0)
    candidate = _doc("D001", [("text", "x")], total_sections=2, total_blocks=3, table_blocks=1)
    diff = parity.diff_doc(golden, candidate)

    joined = "\n".join(diff.reasons)
    assert "total_sections: 1 → 2" in joined
    assert "total_blocks: 1 → 3" in joined
    assert "table_blocks: 0 → 1" in joined


def test_diff_doc_reports_parse_method_fallback():
    # 해시·구조는 같고 추출 경로만 폴백 전환 — 회귀의 강한 신호.
    golden = _doc("D001", [("text", "x")], parse_method="A1_inprocess_api")
    candidate = _doc("D001", [("text", "x")], parse_method="B_libreoffice_docx")
    diff = parity.diff_doc(golden, candidate)

    joined = "\n".join(diff.reasons)
    assert "parse_method: A1_inprocess_api → B_libreoffice_docx" in joined


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
        [
            _doc("D001", [("text", "x")]),
            _doc("D002", [("text", "same")], dedup_hash="sha256:aaa"),
        ],
    )
    candidate_dir = _write_docs(
        tmp_path / "candidate",
        [
            _doc("D002", [("text", "changed")], dedup_hash="sha256:bbb"),
            _doc("D003", [("text", "z")]),
        ],
    )

    diffs, golden_only, candidate_only = parity.compare_dirs(golden_dir, candidate_dir)

    assert golden_only == ["D001"]
    assert candidate_only == ["D003"]
    # 공통은 D002 하나이며, 해시가 달라 불일치로 잡혀야 한다.
    assert [d.doc_id for d in diffs] == ["D002"]
    assert not diffs[0].ok
