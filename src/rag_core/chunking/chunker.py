import math
from rag_core.schemas import Document, Chunk


def clean(val):
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return val


def build_payload(doc: dict, section: dict, block: dict) -> dict:
    meta = doc.get("metadata", {})
    return {
        "doc_id": str(clean(doc.get("doc_id"))),
        "file_name": str(clean(doc.get("file_name"))),
        "source_format": str(clean(doc.get("source_format"))),
        "사업명": str(clean(meta.get("사업명"))),
        "발주기관": str(clean(meta.get("발주기관"))),
        "사업유형": str(clean(meta.get("사업유형"))),
        "사업금액": float(clean(meta.get("사업금액")) or 0.0),
        "공고번호": str(clean(meta.get("공고번호"))),
        "공고차수": float(clean(meta.get("공고차수")) or 0.0),
        "공개일자": str(clean(meta.get("공개일자"))),
        "입찰참여시작일": str(clean(meta.get("입찰참여시작일"))),
        "입찰참여마감일": str(clean(meta.get("입찰참여마감일"))),
        "재공고여부": bool(meta.get("재공고여부", False)),
        "linked_doc_id": str(clean(meta.get("linked_doc_id"))),
        "사업요약": str(clean(meta.get("사업요약"))),
        "header_path": " > ".join(section.get("header_path", [])),
        "section_id": str(clean(section.get("section_id"))),
        "block_id": str(clean(block.get("block_id"))),
        "block_type": str(clean(block.get("type"))),
        "table_type": str(clean(block.get("table_type"))),
    }


class Chunker:
    MAX_CHUNK_SIZE = 500
    OVERLAP = 100

    def chunk(self, document: Document) -> list[Chunk]:
        result = []
        doc = document.metadata

        warnings = doc.get("qa", {}).get("extraction_warnings", [])
        if warnings:
            print(f"  [WARN] {document.doc_id} — extraction_warnings: {warnings}")

        meta = doc.get("metadata", {})
        사업명 = str(clean(meta.get("사업명", "")))
        발주기관 = str(clean(meta.get("발주기관", "")))

        prefix = f"[사업명] {사업명}\n[발주기관] {발주기관}\n\n"

        for section in doc.get("sections", []):
            chunks = self._chunk_section(section)
            for item in chunks:
                result.append(
                    Chunk(
                        chunk_id=item["block"].get("block_id", "") if item["block"] else "",
                        doc_id=document.doc_id,
                        text=prefix + item["content"],
                        metadata=build_payload(doc, section, item["block"] or {}),
                    )
                )
        return result

    def _chunk_section(self, section: dict) -> list[dict]:
        header_prefix = " > ".join(section.get("header_path", []))
        results = []
        current_text = ""
        last_text_block = None

        for block in section.get("blocks", []):
            if block.get("is_decorative"):
                continue

            if block["type"] == "table":
                if current_text.strip():
                    # 직전 텍스트와 테이블 병합
                    merged = current_text.strip() + "\n\n" + block["content"]
                    results.append(
                        {
                            "content": f"[섹션: {header_prefix}]\n\n{merged}",
                            "block": block,
                        }
                    )
                    # overlap: 현재 텍스트 끝부분 유지
                    current_text = (
                        current_text[-self.OVERLAP :]
                        if len(current_text) > self.OVERLAP
                        else current_text
                    )
                    last_text_block = None
                else:
                    results.append(
                        {
                            "content": f"[섹션: {header_prefix}]\n\n{block['content']}",
                            "block": block,
                        }
                    )
            else:
                if (
                    len(current_text) + len(block["content"]) > self.MAX_CHUNK_SIZE
                    and current_text.strip()
                ):
                    results.append(
                        {
                            "content": f"[섹션: {header_prefix}]\n\n{current_text.strip()}",
                            "block": last_text_block,
                        }
                    )
                    # overlap: 이전 청크 끝부분을 다음 청크 시작에 포함
                    current_text = current_text[-self.OVERLAP :] + block["content"] + "\n\n"
                else:
                    current_text += block["content"] + "\n\n"
                last_text_block = block

        if current_text.strip():
            results.append(
                {
                    "content": f"[섹션: {header_prefix}]\n\n{current_text.strip()}",
                    "block": last_text_block,
                }
            )

        return results
