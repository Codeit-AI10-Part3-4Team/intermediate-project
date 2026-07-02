"""
RAG 전처리 파이프라인 (통합 단일 파일)
======================================
새 문서가 들어왔을 때 동일한 파싱 → JSON 변환 흐름을 재현합니다.

파싱 방식 우선순위 (D043 방식 기준):
  HWP: [A-1] hwp5.xmlmodel.Hwp5File Python API (BSTR 패치 포함)
       [A-2] hwp5proc txt (폴백)
       [B]   LibreOffice HWP→DOCX (최후 폴백)
  PDF: pdfplumber (표 영역 분리 추출)

사용법 1 — 단일 파일 처리 (CSV 없이):
  python pipeline.py --file ./files/문서.hwp --output_dir ./output

사용법 2 — CSV 기반 전체/다건 처리:
  python pipeline.py --files_dir ./files --csv_path ./data_list.csv --output_dir ./output
  python pipeline.py --files_dir ./files --csv_path ./data_list.csv --output_dir ./output --doc_ids D001 D002

의존 라이브러리 설치:
  pip install pyhwp==0.1b15 pdfplumber lxml pandas python-docx
"""

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
from lxml import etree

# ─────────────────────────────────────────────────────────────
# pyhwp BSTR 서로게이트 패치
# Python API(Hwp5File) 직접 호출 시 같은 프로세스에서 패치 동작
# ─────────────────────────────────────────────────────────────
PYHWP_AVAILABLE = False
try:
    import hwp5.dataio as _hwp5_dio

    def _safe_decode_utf16le(data: bytes) -> str:
        try:
            return data.decode("utf-16-le")
        except UnicodeDecodeError:
            return data.decode("utf-16-le", errors="replace")

    _hwp5_dio.decode_utf16le_with_hypua = _safe_decode_utf16le
    PYHWP_AVAILABLE = True
    print("[패치 완료] pyhwp BSTR 서로게이트 오류 무시 모드 적용")
except ImportError:
    print("[경고] pyhwp 미설치 — LibreOffice 폴백으로만 HWP 파싱 진행합니다.")
    print("       (pyhwp 설치 원하면: pip install pyhwp==0.1b15)")

PDFPLUMBER_AVAILABLE = False
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    print("[경고] pdfplumber 미설치 — PDF 파싱 불가. pip install pdfplumber")


# ══════════════════════════════════════════════════════════════
# 1. 공통 상수 & 헬퍼
# ══════════════════════════════════════════════════════════════

UNKNOWN = "<unknown>"

HEADER_PATTERNS = [
    (1, re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVXIVX]+[\s\.·]")),
    (1, re.compile(r"^제\s*\d+\s*장\s")),
    (2, re.compile(r"^\d+\.\s+[가-힣A-Za-z]")),
    (2, re.compile(r"^□\s")),
    (3, re.compile(r"^\s{0,4}[가나다라마바사아자차카타파하]\.\s")),
    (3, re.compile(r"^\s{0,4}\d+\)\s")),
]

SKIP_CONTROL_TAGS = {"TableControl", "GShapeObjectControl", "EqEdit", "ShapeComponent"}
NUMERIC_PATTERN = re.compile(r"^[\d,\.\-/%원₩()]+$")

TYPE_KW = [
    ("재구축", "재구축"), ("고도화", "고도화"), ("개선", "개선"),
    ("개발", "개발"), ("운영", "운영"), ("통합", "통합"), ("구축", "구축"),
]

TOC_PATTERN = re.compile(
    r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVXIVX]+[^\n]{2,40}?|\d+\.\s[가-힣A-Za-z][^\n]{2,40}?)"
    r"[\s·\-·⋯\.]{3,}\s*\d+",
    re.MULTILINE,
)


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", str(s).strip())


def detect_header_level(line: str) -> int:
    s = line.strip()
    if len(s) > 80:
        return 0
    for lv, pat in HEADER_PATTERNS:
        if pat.match(s):
            return lv
    return 0


def infer_type(name: str) -> str:
    for kw, lb in TYPE_KW:
        if kw in str(name):
            return lb
    return "기타"


def extract_toc(text: str) -> list:
    return [m.strip() for m in TOC_PATTERN.findall(str(text))][:30]


# ══════════════════════════════════════════════════════════════
# 2. 표 유틸리티
# ══════════════════════════════════════════════════════════════

def cell_text(cell) -> str:
    return " ".join("".join(cell.itertext()).split())


def reconstruct_grid(table_el) -> list:
    rows = int(table_el.get("rows", 1))
    cols = int(table_el.get("cols", 1))
    grid = [["" for _ in range(cols)] for _ in range(rows)]
    for cell in table_el.findall(".//TableCell"):
        r  = int(cell.get("row", 0))
        c  = int(cell.get("col", 0))
        rs = int(cell.get("rowspan", 1))
        cs = int(cell.get("colspan", 1))
        txt = cell_text(cell)
        for rr in range(r, min(r + rs, rows)):
            for cc in range(c, min(c + cs, cols)):
                grid[rr][cc] = txt
    return grid


def classify_table(grid: list) -> str:
    if not grid:
        return "wide"
    if len(grid[0]) == 2 and len(grid) >= 2:
        first_col = [r[0] for r in grid if r[0]]
        if first_col and sum(len(v) for v in first_col) / len(first_col) < 20:
            return "key_value"
    return "wide"


def grid_to_markdown(grid: list) -> str:
    if not grid:
        return ""
    cols = len(grid[0])
    lines = [
        "| " + " | ".join(grid[0]) + " |",
        "| " + " | ".join(["---"] * cols) + " |",
    ]
    for row in grid[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def grid_to_kv(grid: list) -> str:
    return " ".join(
        f"{r[0]}: {r[1]}."
        for r in grid if len(r) >= 2 and r[0]
    )


def serialize_table(grid: list) -> tuple:
    t_type = classify_table(grid)
    if t_type == "key_value":
        return t_type, grid_to_kv(grid), "세로형 2열 표 → 키-값 문장으로 직렬화"
    return t_type, grid_to_markdown(grid), "가로형 표 → Markdown으로 직렬화"


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s))


def _table_plain_text(grid: list) -> str:
    return "".join(c for row in grid for c in row if c)


def _text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _internal_repetition_ratio(grid: list) -> float:
    cells = [_norm(c) for row in grid for c in row if c.strip()]
    if not cells:
        return 0.0
    return 1 - (len(set(cells)) / len(cells))


def _numeric_cell_ratio(grid: list) -> float:
    cells = [c.strip() for row in grid for c in row if c.strip()]
    if not cells:
        return 0.0
    return sum(1 for c in cells if NUMERIC_PATTERN.match(c)) / len(cells)


def classify_decorative(grid: list, prev_block: dict) -> tuple:
    n_rows = len(grid)
    n_cols = len(grid[0]) if grid else 0
    if n_rows == 1 and n_cols == 1:
        return True, f"tiny_table(rows={n_rows},cols={n_cols})"
    plain = _norm(_table_plain_text(grid))
    sim = 0.0
    if prev_block is not None and prev_block.get("type") == "text":
        sim = _text_similarity(plain, _norm(prev_block["content"]))
        if sim >= 0.97:
            return True, f"text_overlap={sim:.2f}"
    rep  = _internal_repetition_ratio(grid)
    numr = _numeric_cell_ratio(grid)
    if rep >= 0.5 and numr < 0.1:
        return True, f"internal_repetition={rep:.2f}"
    return False, f"data_table(sim={sim:.2f},rep={rep:.2f},numeric={numr:.2f})"


def dedup_merged_cells(raw_grid: list) -> list:
    cleaned = []
    for row in raw_grid:
        new_row, prev = [], object()
        for cell in row:
            if cell == prev:
                continue
            new_row.append(cell)
            prev = cell
        cleaned.append(new_row)
    return cleaned


def clean_tables_in_doc(sections: list) -> int:
    changed = 0
    for section in sections:
        for block in section["blocks"]:
            if block.get("type") != "table":
                continue
            before = block.get("raw_grid", [])
            after  = dedup_merged_cells(before)
            if after != before:
                block["raw_grid"] = after
                block["content"]  = grid_to_markdown(after)
                changed += 1
            flat = [c for row in block["raw_grid"] for c in row]
            if len(block["raw_grid"]) <= 1 and len(flat) <= 1 and not block.get("is_decorative"):
                block["is_decorative"]    = True
                block["decorative_reason"] = "dedup_collapsed_to_single_cell"
    return changed


def flag_large_sections(sections: list, threshold: int = 30) -> int:
    flagged = 0
    for section in sections:
        bc = len(section["blocks"])
        section["block_count"]   = bc
        section["needs_subsplit"] = bc > threshold
        if section["needs_subsplit"]:
            flagged += 1
    return flagged


# ══════════════════════════════════════════════════════════════
# 3. 섹션 빌드 공통 로직
# ══════════════════════════════════════════════════════════════

def _flush_section(sections, sec_counter, headers, level, blocks):
    if not blocks:
        return sec_counter
    sec_counter += 1
    sec_id = f"S{sec_counter:02d}"
    renumbered = []
    for i, blk in enumerate(blocks, start=1):
        blk = dict(blk)
        blk["block_id"] = f"{sec_id}-B{i:02d}"
        renumbered.append(blk)
    sections.append({
        "section_id":       sec_id,
        "header_path":      list(headers),
        "level":            level,
        "blocks":           renumbered,
        "toc_ref":          None,
        "toc_match_failed": True,
    })
    return sec_counter


def _body_items_to_sections(body_items: list, warnings: list) -> tuple:
    sections = []
    headers  = ["(서두)"]
    level    = 0
    blocks   = []
    sec_counter = blk_counter = text_count = table_count = 0
    wide_count = kv_count = decorative_count = 0

    for itype, ival in body_items:
        if itype == "text":
            lv = detect_header_level(ival)
            if lv > 0:
                sec_counter = _flush_section(sections, sec_counter, headers, level, blocks)
                blocks = []
                if lv == 1:   headers = [ival.strip()]
                elif lv == 2: headers = headers[:1] + [ival.strip()]
                else:         headers = headers[:2] + [ival.strip()]
                level = lv
            else:
                blk_counter += 1
                text_count  += 1
                blocks.append({
                    "block_id": f"B{blk_counter:04d}",
                    "type":     "text",
                    "content":  ival,
                })
        else:
            grid = reconstruct_grid(ival)
            if not grid or not any(any(c for c in r) for r in grid):
                warnings.append(f"빈 표 감지 (blk#{blk_counter+1})")
                continue
            t_type, content, note = serialize_table(grid)
            if not content.strip():
                warnings.append(f"표 직렬화 빈 결과 (blk#{blk_counter+1})")
                continue
            blk_counter += 1
            table_count += 1
            wide_count  += 1 if t_type == "wide" else 0
            kv_count    += 1 if t_type == "key_value" else 0
            prev_block   = blocks[-1] if blocks else None
            is_dec, dec_reason = classify_decorative(grid, prev_block)
            if is_dec:
                decorative_count += 1
            blocks.append({
                "block_id":          f"B{blk_counter:04d}",
                "type":              "table",
                "table_type":        t_type,
                "content":           content,
                "note":              note,
                "raw_grid":          grid,
                "is_decorative":     is_dec,
                "decorative_reason": dec_reason,
            })

    _flush_section(sections, sec_counter, headers, level, blocks)

    qa = {
        "total_sections":         len(sections),
        "total_blocks":           blk_counter,
        "text_blocks":            text_count,
        "table_blocks":           table_count,
        "table_wide_count":       wide_count,
        "table_key_value_count":  kv_count,
        "decorative_table_count": decorative_count,
        "decorative_table_ratio": round(decorative_count / table_count, 3) if table_count else 0.0,
        "extraction_warnings":    warnings,
    }
    return sections, qa


def _empty_qa(warning_msg: str) -> dict:
    return {
        "total_sections": 0, "total_blocks": 0, "text_blocks": 0,
        "table_blocks": 0, "table_wide_count": 0, "table_key_value_count": 0,
        "decorative_table_count": 0, "decorative_table_ratio": 0.0,
        "extraction_warnings": [warning_msg],
    }


# ══════════════════════════════════════════════════════════════
# 4. HWP 파싱
# ══════════════════════════════════════════════════════════════

def paragraph_own_text(para_el) -> str:
    texts = []
    def walk(el):
        for child in el:
            if child.tag in SKIP_CONTROL_TAGS:
                continue
            if child.tag == "Text" and child.text:
                texts.append(child.text)
            walk(child)
    walk(para_el)
    return " ".join("".join(texts).split())


def _xml_to_sections(xml_bytes: bytes) -> tuple:
    warnings = []
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        try:
            root = etree.fromstring(xml_bytes, etree.XMLParser(recover=True))
            warnings.append(f"XML recover 모드 사용: {e}")
        except Exception as e2:
            return None, f"XML 파싱 실패: {e2}"

    body_items = []
    for el in root.iter():
        if el.tag == "TableBody":
            body_items.append(("table", el))
        elif el.tag == "Paragraph":
            if "TableCell" not in {p.tag for p in el.iterancestors()}:
                txt = paragraph_own_text(el)
                if txt:
                    body_items.append(("text", txt))

    if not body_items:
        return None, "body_items 없음"

    sections, qa = _body_items_to_sections(body_items, warnings)
    return (sections, qa), None


def parse_hwp_inprocess(hwp_path: Path) -> tuple:
    """[A-1] hwp5.xmlmodel.Hwp5File Python API 직접 호출"""
    if not PYHWP_AVAILABLE:
        return None, "pyhwp 미설치"
    try:
        from hwp5.xmlmodel import Hwp5File
        buf = io.BytesIO()
        hwp = Hwp5File(str(hwp_path))
        hwp.bodytext.xmlevents().dump(buf)
        xml_bytes = buf.getvalue()
    except Exception as e:
        return None, f"Hwp5File API 실패: {e}"

    if not xml_bytes.strip():
        return None, "XML 버퍼 비어있음"

    result, err = _xml_to_sections(xml_bytes)
    if result is not None:
        result[1]["parse_method"] = "A1_inprocess_api"
    return result, err


def parse_hwp_txt(hwp_path: Path) -> tuple:
    """[A-2] hwp5proc txt 텍스트 전용 폴백"""
    if not PYHWP_AVAILABLE:
        return None, "pyhwp 미설치"
    try:
        result = subprocess.run(
            ["hwp5proc", "txt", str(hwp_path)],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0:
            return None, f"hwp5proc txt 오류: {result.stderr.decode('utf-8', errors='replace')[:300]}"
        raw_text = result.stdout.decode("utf-8", errors="replace")
        if not raw_text.strip():
            return None, "hwp5proc txt 결과 없음"

        body_items = [("text", line.strip()) for line in raw_text.split("\n") if line.strip()]
        warnings   = ["hwp5txt 경로 사용 — 표 구조 미복원"]
        sections, qa = _body_items_to_sections(body_items, warnings)
        qa["parse_method"] = "A2_hwp5txt"
        return (sections, qa), None

    except subprocess.TimeoutExpired:
        return None, "hwp5proc txt 타임아웃(120s)"
    except Exception as e:
        return None, f"hwp5proc txt 예외: {e}"


def _find_soffice() -> str:
    """윈도우/맥/리눅스에서 soffice 실행 경로 탐색"""
    candidates = [
        "soffice",  # PATH에 등록된 경우
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for c in candidates:
        try:
            r = subprocess.run([c, "--version"], capture_output=True, timeout=10)
            if r.returncode == 0:
                return c
        except Exception:
            continue
    return None


def parse_hwp_libreoffice(hwp_path: Path) -> tuple:
    """[B] LibreOffice HWP→DOCX→python-docx 최후 폴백 (윈도우/맥/리눅스 공용)"""
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except ImportError:
        return None, "python-docx 미설치. pip install python-docx"

    soffice = _find_soffice()
    if soffice is None:
        return None, (
            "LibreOffice를 찾을 수 없습니다.\n"
            "설치 후 재시도하세요: https://www.libreoffice.org/download/\n"
            "설치 후 PATH에 soffice 경로 추가 필요 (예: C:\\Program Files\\LibreOffice\\program)"
        )

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            r = subprocess.run(
                [soffice, "--headless", "--convert-to", "docx",
                 "--outdir", tmp_dir, str(hwp_path)],
                capture_output=True, timeout=180,
            )
            if r.returncode != 0:
                return None, f"soffice 변환 실패: {r.stderr.decode(errors='replace')[:300]}"
            docx_path = Path(tmp_dir) / (hwp_path.stem + ".docx")
            if not docx_path.exists():
                return None, f"변환 결과 파일 없음: {docx_path}"

            doc      = Document(str(docx_path))
            sections = []
            headers  = ["(서두)"]
            level    = 0
            blocks   = []
            sec_counter = blk_counter = text_count = table_count = 0
            wide_count = kv_count = decorative_count = 0
            warnings = ["LibreOffice 변환 경로 사용 — 표 병합 셀 근사 복원"]

            for element in doc.element.body:
                tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

                if tag == "p":
                    txt = "".join(
                        node.text for node in element.iter()
                        if node.tag.endswith("}t") and node.text
                    ).strip()
                    if not txt:
                        continue
                    lv = detect_header_level(txt)
                    if lv > 0:
                        sec_counter = _flush_section(sections, sec_counter, headers, level, blocks)
                        blocks = []
                        if lv == 1:   headers = [txt.strip()]
                        elif lv == 2: headers = headers[:1] + [txt.strip()]
                        else:         headers = headers[:2] + [txt.strip()]
                        level = lv
                    else:
                        blk_counter += 1
                        text_count  += 1
                        blocks.append({
                            "block_id": f"B{blk_counter:04d}",
                            "type": "text", "content": txt,
                        })

                elif tag == "tbl":
                    rows_data = []
                    for tr in element.findall(".//" + qn("w:tr")):
                        row = [
                            "".join(
                                n.text for n in tc.iter()
                                if n.tag.endswith("}t") and n.text
                            ).strip()
                            for tc in tr.findall(".//" + qn("w:tc"))
                        ]
                        if row:
                            rows_data.append(row)
                    if not rows_data:
                        continue
                    max_cols = max(len(r) for r in rows_data)
                    grid     = [r + [""] * (max_cols - len(r)) for r in rows_data]
                    if not any(any(c for c in r) for r in grid):
                        continue
                    t_type, content, note = serialize_table(grid)
                    if not content.strip():
                        continue
                    blk_counter += 1
                    table_count += 1
                    wide_count  += 1 if t_type == "wide" else 0
                    kv_count    += 1 if t_type == "key_value" else 0
                    prev_block   = blocks[-1] if blocks else None
                    is_dec, dec_reason = classify_decorative(grid, prev_block)
                    if is_dec:
                        decorative_count += 1
                    blocks.append({
                        "block_id": f"B{blk_counter:04d}", "type": "table",
                        "table_type": t_type, "content": content, "note": note,
                        "raw_grid": grid, "is_decorative": is_dec,
                        "decorative_reason": dec_reason,
                    })

            _flush_section(sections, sec_counter, headers, level, blocks)

            qa = {
                "total_sections":         len(sections),
                "total_blocks":           blk_counter,
                "text_blocks":            text_count,
                "table_blocks":           table_count,
                "table_wide_count":       wide_count,
                "table_key_value_count":  kv_count,
                "decorative_table_count": decorative_count,
                "decorative_table_ratio": round(decorative_count / table_count, 3) if table_count else 0.0,
                "extraction_warnings":    warnings,
                "parse_method":           "B_libreoffice_docx",
            }
            return (sections, qa), None

    except subprocess.TimeoutExpired:
        return None, "soffice 타임아웃(180s)"
    except Exception as e:
        return None, f"LibreOffice 파싱 예외: {e}"


def parse_hwp(hwp_path: Path) -> tuple:
    """HWP 통합 진입점: A-1 → A-2 → B 순서로 시도"""
    result, err1 = parse_hwp_inprocess(hwp_path)
    if result is not None:
        print(f"    → A-1 (Hwp5File API) 성공")
        return result

    print(f"    → A-1 실패: {err1}")
    result, err2 = parse_hwp_txt(hwp_path)
    if result is not None:
        print(f"    → A-2 (hwp5txt) 성공")
        return result

    print(f"    → A-2 실패: {err2}")
    print(f"    → B (LibreOffice) 시도...")
    result, err3 = parse_hwp_libreoffice(hwp_path)
    if result is not None:
        print(f"    → B (LibreOffice) 성공")
        return result

    print(f"    → B 실패: {err3}")
    return [], _empty_qa(f"모든 파싱 실패: A1={err1} | A2={err2} | B={err3}")


# ══════════════════════════════════════════════════════════════
# 5. PDF 파싱
# ══════════════════════════════════════════════════════════════

def pdf_clean_grid(raw_table: list) -> list:
    cleaned, prev_first = [], ""
    for row in raw_table:
        new_row = []
        for i, cell in enumerate(row):
            val = str(cell).strip() if cell is not None else ""
            if i == 0:
                val = val if val else prev_first
                prev_first = val
            val = re.sub(r"\s+", " ", val.replace("\n", " ").replace("\xad", "-"))
            new_row.append(val)
        if any(c for c in new_row):
            cleaned.append(new_row)
    return cleaned


def parse_pdf(pdf_path: Path) -> tuple:
    if not PDFPLUMBER_AVAILABLE:
        return [], _empty_qa("pdfplumber 미설치 — pip install pdfplumber")

    sections = []
    headers  = ["(서두)"]
    level    = 0
    blocks   = []
    sec_counter = blk_counter = text_count = table_count = 0
    wide_count = kv_count = decorative_count = 0
    warnings = []

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                page_tables = page.extract_tables()
                try:
                    table_bboxes = [t.bbox for t in page.find_tables()]
                except Exception:
                    table_bboxes = []

                if table_bboxes:
                    filtered = page
                    for bbox in table_bboxes:
                        filtered = filtered.filter(
                            lambda obj, b=bbox: not (
                                obj.get("x0", 0) >= b[0] and obj.get("x1", 0) <= b[2] and
                                obj.get("top", 0) >= b[1] and obj.get("bottom", 0) <= b[3]
                            )
                        )
                    raw_text = filtered.extract_text() or ""
                else:
                    raw_text = page.extract_text() or ""

                for line in raw_text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    lv = detect_header_level(line)
                    if lv > 0:
                        sec_counter = _flush_section(sections, sec_counter, headers, level, blocks)
                        blocks = []
                        if lv == 1:   headers = [line]
                        elif lv == 2: headers = headers[:1] + [line]
                        else:         headers = headers[:2] + [line]
                        level = lv
                    else:
                        blk_counter += 1
                        text_count  += 1
                        blocks.append({
                            "block_id": f"B{blk_counter:04d}",
                            "type": "text", "content": line,
                        })

                for raw_table in page_tables:
                    grid = pdf_clean_grid(raw_table)
                    if not grid:
                        continue
                    t_type, content, note = serialize_table(grid)
                    if not content.strip():
                        continue
                    blk_counter += 1
                    table_count += 1
                    wide_count  += 1 if t_type == "wide" else 0
                    kv_count    += 1 if t_type == "key_value" else 0
                    prev_block   = blocks[-1] if blocks else None
                    is_dec, dec_reason = classify_decorative(grid, prev_block)
                    if is_dec:
                        decorative_count += 1
                    blocks.append({
                        "block_id": f"B{blk_counter:04d}", "type": "table",
                        "table_type": t_type, "content": content, "note": note,
                        "raw_grid": grid, "is_decorative": is_dec,
                        "decorative_reason": dec_reason,
                    })

    except Exception as e:
        warnings.append(f"PDF 파싱 오류: {e}")

    _flush_section(sections, sec_counter, headers, level, blocks)

    return sections, {
        "total_sections":         len(sections),
        "total_blocks":           blk_counter,
        "text_blocks":            text_count,
        "table_blocks":           table_count,
        "table_wide_count":       wide_count,
        "table_key_value_count":  kv_count,
        "decorative_table_count": decorative_count,
        "decorative_table_ratio": round(decorative_count / table_count, 3) if table_count else 0.0,
        "extraction_warnings":    warnings,
        "parse_method":           "pdfplumber",
    }


# ══════════════════════════════════════════════════════════════
# 6. JSON 빌드
# ══════════════════════════════════════════════════════════════

def compute_toc_match_rate(toc: list, sections: list) -> float:
    if not toc:
        return 0.0
    all_headers = " ".join(h for s in sections for h in s["header_path"])
    matched = sum(1 for t in toc if t[:6] in all_headers)
    return round(matched / len(toc), 2)


def build_json(row: pd.Series, sections: list, qa_info: dict, toc: list) -> dict:
    all_text = " ".join(b["content"] for s in sections for b in s["blocks"])
    qa_info["toc_header_match_rate"] = compute_toc_match_rate(toc, sections)
    qa_info["dedup_hash"]            = "sha256:" + hashlib.sha256(all_text.encode()).hexdigest()
    qa_info["needs_subsplit_count"]  = sum(1 for s in sections if s.get("needs_subsplit"))

    if qa_info.get("decorative_table_ratio", 0.0) > 0.15:
        qa_info["extraction_warnings"].append(
            f'high_decorative_table_ratio: {qa_info["decorative_table_ratio"]:.1%}'
        )

    return {
        "schema_version": "1.0",
        "doc_id":         row["doc_id"],
        "file_name":      str(row["파일명"]),
        "source_format":  str(row["파일형식"]).lower(),
        "processed_at":   str(date.today()),
        "metadata": {
            "공고번호":       row["공고번호"],
            "공고차수":       int(row["공고차수"]),
            "사업명":         row["사업명"],
            "사업금액":       int(row["사업금액"]) if pd.notna(row["사업금액"]) else None,
            "발주기관":       row["발주기관"],
            "공개일자":       row["공개일자"],
            "입찰참여시작일": row["입찰참여시작일"],
            "입찰참여마감일": row["입찰참여마감일"],
            "사업요약":       row["사업요약"],
            "사업유형":       row["사업유형"],
            "재공고여부":     bool(row["재공고여부"]),
            "linked_doc_id":  None,
            "목차존재":       len(toc) > 0,
        },
        "toc":      toc,
        "sections": sections,
        "qa":       qa_info,
    }


def build_json_single(file_path: Path, sections: list, qa_info: dict, toc: list) -> dict:
    """CSV 없이 단일 파일만 처리할 때 사용하는 JSON 빌드"""
    fmt = file_path.suffix.lstrip(".").lower()
    all_text = " ".join(b["content"] for s in sections for b in s["blocks"])
    qa_info["toc_header_match_rate"] = compute_toc_match_rate(toc, sections)
    qa_info["dedup_hash"]            = "sha256:" + hashlib.sha256(all_text.encode()).hexdigest()
    qa_info["needs_subsplit_count"]  = sum(1 for s in sections if s.get("needs_subsplit"))

    if qa_info.get("decorative_table_ratio", 0.0) > 0.15:
        qa_info["extraction_warnings"].append(
            f'high_decorative_table_ratio: {qa_info["decorative_table_ratio"]:.1%}'
        )

    return {
        "schema_version": "1.0",
        "doc_id":         file_path.stem,
        "file_name":      file_path.name,
        "source_format":  fmt,
        "processed_at":   str(date.today()),
        "metadata": {
            "공고번호":       UNKNOWN,
            "공고차수":       0,
            "사업명":         file_path.stem,
            "사업금액":       None,
            "발주기관":       UNKNOWN,
            "공개일자":       UNKNOWN,
            "입찰참여시작일": UNKNOWN,
            "입찰참여마감일": UNKNOWN,
            "사업요약":       UNKNOWN,
            "사업유형":       infer_type(file_path.stem),
            "재공고여부":     False,
            "linked_doc_id":  None,
            "목차존재":       len(toc) > 0,
        },
        "toc":      toc,
        "sections": sections,
        "qa":       qa_info,
    }


# ══════════════════════════════════════════════════════════════
# 7. CSV 전처리
# ══════════════════════════════════════════════════════════════

def load_and_preprocess_csv(csv_path: Path, files_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    df.columns = [
        "공고번호", "공고차수", "사업명", "사업금액", "발주기관",
        "공개일자", "입찰참여시작일", "입찰참여마감일",
        "사업요약", "파일형식", "파일명", "텍스트",
    ]
    print(f"원본 행 수: {len(df)}")

    drop_mask = df["파일명"].str.contains("한국한의학연구원", na=False)
    print(f"제거 대상: {drop_mask.sum()}건")
    df = df[~drop_mask].reset_index(drop=True)

    df["_hash"] = df["텍스트"].apply(lambda x: hashlib.md5(str(x).encode()).hexdigest())
    before = len(df)
    df = df.drop_duplicates(subset="_hash", keep="first").reset_index(drop=True)
    print(f"해시 중복 제거: {before - len(df)}건")

    df["doc_id"] = [f"D{str(i+1).zfill(3)}" for i in range(len(df))]

    for col in ["공고번호", "공개일자", "입찰참여시작일", "입찰참여마감일", "사업요약"]:
        df[col] = df[col].fillna(UNKNOWN).astype(str)
    df["공고차수"] = df["공고차수"].fillna(0).astype(int)
    df["사업금액"] = df["사업금액"].where(df["사업금액"].notna(), other=None)

    df["사업유형"] = df["사업명"].apply(infer_type)
    df["재공고여부"] = df["공고차수"] > 0

    all_files = list(files_dir.iterdir())
    file_map  = {nfc(f.name): f for f in all_files}
    df["file_path"] = df["파일명"].apply(
        lambda x: file_map.get(nfc(x)) if not pd.isna(x) else None
    )

    success = df["file_path"].notna().sum()
    print(f"파일 매핑: {success}건 성공 / {len(df) - success}건 실패")
    return df


# ══════════════════════════════════════════════════════════════
# 8. 단일 파일 파이프라인
# ══════════════════════════════════════════════════════════════

def run_single_file(file_path: Path, output_dir: Path):
    """CSV 없이 파일 하나만 처리"""
    docs_dir = output_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    fmt = file_path.suffix.lstrip(".").lower()
    print(f"\n[단일 파일 처리] {file_path.name}")

    if not file_path.exists():
        print(f"  ❌ 파일 없음: {file_path}")
        return

    if fmt == "hwp":
        sections, qa_info = parse_hwp(file_path)
    elif fmt == "pdf":
        sections, qa_info = parse_pdf(file_path)
    else:
        print(f"  ❌ 미지원 형식: {fmt} (hwp 또는 pdf만 가능)")
        return

    if qa_info.get("total_sections", 0) == 0:
        reason = (qa_info.get("extraction_warnings") or ["알 수 없는 파싱 실패"])[0]
        print(f"  ❌ 파싱 결과 없음: {reason}")
        return

    clean_tables_in_doc(sections)
    flag_large_sections(sections, threshold=30)

    doc_json = build_json_single(file_path, sections, qa_info, toc=[])
    out_path = docs_dir / f"{file_path.stem}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc_json, f, ensure_ascii=False, indent=2)

    method   = qa_info.get("parse_method", "?")
    has_warn = len(qa_info["extraction_warnings"]) > 0
    print(
        f"  ✅ [{method}]  "
        f"섹션={qa_info['total_sections']}  "
        f"블록={qa_info['total_blocks']}  "
        f"표={qa_info['table_blocks']}  "
        f"{'⚠️ ' + str(qa_info['extraction_warnings']) if has_warn else ''}"
    )
    print(f"  저장: {out_path}")


# ══════════════════════════════════════════════════════════════
# 9. CSV 기반 전체 파이프라인
# ══════════════════════════════════════════════════════════════

def run_pipeline(files_dir: Path, csv_path: Path, output_dir: Path, doc_ids: list = None):
    docs_dir = output_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    df = load_and_preprocess_csv(csv_path, files_dir)
    if doc_ids:
        df = df[df["doc_id"].isin(doc_ids)].reset_index(drop=True)
        print(f"필터링 후: {len(df)}건")

    manifest_rows = []
    failed_docs   = []

    for _, row in df.iterrows():
        doc_id    = row["doc_id"]
        file_path = row["file_path"]
        fmt       = str(row["파일형식"]).lower()

        print(f"\n[{doc_id}] {str(row['사업명'])[:45]}")

        if file_path is None or not Path(str(file_path)).exists():
            msg = f"파일 없음: {file_path}"
            print(f"  ❌ {msg}")
            failed_docs.append({"doc_id": doc_id, "사업명": row["사업명"], "원인": msg})
            continue

        try:
            if fmt == "hwp":
                sections, qa_info = parse_hwp(Path(str(file_path)))
            elif fmt == "pdf":
                sections, qa_info = parse_pdf(Path(str(file_path)))
            else:
                msg = f"미지원 형식: {fmt}"
                print(f"  ❌ {msg}")
                failed_docs.append({"doc_id": doc_id, "사업명": row["사업명"], "원인": msg})
                continue
        except Exception as e:
            msg = str(e)
            print(f"  ❌ 파싱 예외: {msg}")
            failed_docs.append({"doc_id": doc_id, "사업명": row["사업명"], "원인": msg})
            continue

        if qa_info.get("total_sections", 0) == 0:
            reason = (qa_info.get("extraction_warnings") or ["알 수 없는 파싱 실패"])[0]
            print(f"  ❌ 파싱 결과 없음: {reason}")
            failed_docs.append({"doc_id": doc_id, "사업명": row["사업명"], "원인": reason})
            continue

        tables_cleaned = clean_tables_in_doc(sections)
        flagged_count  = flag_large_sections(sections, threshold=30)
        qa_info["needs_subsplit_count"] = flagged_count

        toc = extract_toc(row.get("텍스트", ""))

        doc_json = build_json(row, sections, qa_info, toc)
        out_path = docs_dir / f"{doc_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(doc_json, f, ensure_ascii=False, indent=2)

        method   = qa_info.get("parse_method", "?")
        has_warn = len(qa_info["extraction_warnings"]) > 0
        print(
            f"  ✅ [{method}]  "
            f"섹션={qa_info['total_sections']}  "
            f"블록={qa_info['total_blocks']}  "
            f"표={qa_info['table_blocks']}  "
            f"표정리={tables_cleaned}건  "
            f"{'⚠️' if has_warn else ''}"
        )

        manifest_rows.append({
            "doc_id":         doc_id,
            "파일명":          row["파일명"],
            "사업명":          row["사업명"],
            "발주기관":        row["발주기관"],
            "사업유형":        row["사업유형"],
            "사업금액":        row["사업금액"],
            "공개일자":        row["공개일자"],
            "파일형식":        fmt,
            "재공고여부":      row["재공고여부"],
            "목차존재":        len(toc) > 0,
            "total_sections": qa_info["total_sections"],
            "total_blocks":   qa_info["total_blocks"],
            "table_blocks":   qa_info["table_blocks"],
            "has_warning":    has_warn,
            "parse_method":   method,
            "json_path":      str(out_path),
        })

    # 재공고 연결
    for mrow in manifest_rows:
        did    = mrow["doc_id"]
        re_row = df[df["doc_id"] == did]
        if re_row.empty:
            continue
        re_row = re_row.iloc[0]
        if not re_row["재공고여부"]:
            continue
        candidates = df[
            (df["사업명"]   == re_row["사업명"])   &
            (df["발주기관"] == re_row["발주기관"]) &
            (df["공고차수"] <  re_row["공고차수"])
        ]
        if candidates.empty:
            continue
        original_id = candidates.sort_values("공고차수").iloc[0]["doc_id"]
        json_path = docs_dir / f"{did}.json"
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            doc["metadata"]["linked_doc_id"] = original_id
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
            print(f"재공고 연결: {did} → {original_id}")

    # manifest 저장
    if manifest_rows:
        manifest_df   = pd.DataFrame(manifest_rows)
        manifest_path = output_dir / "manifest.csv"

        if manifest_path.exists():
            existing = pd.read_csv(manifest_path, encoding="utf-8-sig")
            new_ids  = [r["doc_id"] for r in manifest_rows]
            existing = existing[~existing["doc_id"].isin(new_ids)]
            updated  = pd.concat([existing, manifest_df], ignore_index=True)
            updated.to_csv(manifest_path, index=False, encoding="utf-8-sig")
        else:
            manifest_df.to_csv(manifest_path, index=False, encoding="utf-8-sig")
        print(f"\nmanifest 저장: {manifest_path}")

    if failed_docs:
        fail_df   = pd.DataFrame(failed_docs)
        fail_path = output_dir / "failed_docs.csv"
        fail_df.to_csv(fail_path, index=False, encoding="utf-8-sig")
        print(f"실패 목록 저장: {fail_path}")
        print(fail_df.to_string(index=False))

    print(f"\n=== 완료: {len(manifest_rows)}건 성공 / {len(failed_docs)}건 실패 ===")
    return manifest_rows, failed_docs


# ══════════════════════════════════════════════════════════════
# 10. CLI 진입점
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG 전처리 파이프라인")

    # 단일 파일 모드
    parser.add_argument("--file", default=None, help="단일 파일 경로 (HWP 또는 PDF)")

    # CSV 기반 다건 모드
    parser.add_argument("--files_dir",  default=None, help="원본 HWP/PDF 파일 디렉토리")
    parser.add_argument("--csv_path",   default=None, help="메타데이터 CSV 경로 (data_list.csv)")
    parser.add_argument("--doc_ids", nargs="*", default=None, help="처리할 doc_id 목록 (예: D001 D002)")

    parser.add_argument("--output_dir", required=True, help="JSON 출력 디렉토리")
    args = parser.parse_args()

    if args.file:
        # 단일 파일 모드
        run_single_file(
            file_path  = Path(args.file),
            output_dir = Path(args.output_dir),
        )
    elif args.files_dir and args.csv_path:
        # CSV 기반 다건 모드
        run_pipeline(
            files_dir  = Path(args.files_dir),
            csv_path   = Path(args.csv_path),
            output_dir = Path(args.output_dir),
            doc_ids    = args.doc_ids,
        )
    else:
        print("오류: --file 또는 (--files_dir + --csv_path) 중 하나를 지정하세요.")
        print()
        print("단일 파일:  python pipeline.py --file ./files/문서.hwp --output_dir ./output")
        print("CSV 기반:   python pipeline.py --files_dir ./files --csv_path ./data_list.csv --output_dir ./output")
        sys.exit(1)
