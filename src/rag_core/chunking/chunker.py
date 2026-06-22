import math
from src.rag_core.schemas import Document, Chunk

def clean(val):
    # NaN / None → 빈 문자열 (Chroma 메타데이터는 NaN·None 불가)
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return val


def build_payload(doc: dict, section: dict, block: dict) -> dict:
    meta = doc.get("metadata", {})
    return {
        "doc_id":        str(clean(doc.get("doc_id"))),
        "file_name":     str(clean(doc.get("file_name"))),
        "source_format": str(clean(doc.get("source_format"))),
        "사업명":         str(clean(meta.get("사업명"))),
        "발주기관":       str(clean(meta.get("발주기관"))),
        "사업유형":       str(clean(meta.get("사업유형"))),
        "사업금액":       float(clean(meta.get("사업금액")) or 0.0),
        "공고번호":       str(clean(meta.get("공고번호"))),
        "공고차수":       float(clean(meta.get("공고차수")) or 0.0),
        "공개일자":       str(clean(meta.get("공개일자"))),
        "입찰참여시작일":  str(clean(meta.get("입찰참여시작일"))),
        "입찰참여마감일":  str(clean(meta.get("입찰참여마감일"))),
        "재공고여부":     bool(meta.get("재공고여부", False)),
        "linked_doc_id": str(clean(meta.get("linked_doc_id"))),
        "사업요약":       str(clean(meta.get("사업요약"))),
        "header_path":   " > ".join(section.get("header_path", [])),
        "section_id":    str(clean(section.get("section_id"))),
        "block_id":      str(clean(block.get("block_id"))),
        "block_type":    str(clean(block.get("type"))),
        "table_type":    str(clean(block.get("table_type"))),
    }


class Chunker:
    MAX_CHUNK_SIZE = 1000

    def chunk(self, document: Document) -> list[Chunk]:
        result = []

        # document.metadata에 JSON 전체가 담겨있음
        doc = document.metadata

        warnings = doc.get("qa", {}).get("extraction_warnings", [])
        if warnings:
            print(f"  [WARN] {document.doc_id} — extraction_warnings: {warnings}")

        meta = doc.get("metadata", {})
        summary  = str(clean(meta.get("사업요약", "")))
        사업명   = str(clean(meta.get("사업명", "")))
        발주기관 = str(clean(meta.get("발주기관", "")))

        for section in doc.get("sections", []):
            chunks = self._chunk_section(section)
            for item in chunks:
                prefix = (
                    f"[사업명] {사업명}\n"
                    f"[발주기관] {발주기관}\n"
                    f"[요약] {summary}\n\n"
                )
                result.append(Chunk(
                    chunk_id=item["block"].get("block_id", "") if item["block"] else "",
                    doc_id=document.doc_id,
                    text=prefix + item["content"],
                    metadata=build_payload(doc, section, item["block"] or {}),
                ))
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
                    results.append({
                        "content": f"[섹션: {header_prefix}]\n\n{current_text.strip()}",
                        "block":   last_text_block,
                    })
                    current_text = ""
                    last_text_block = None
                results.append({
                    "content": f"[섹션: {header_prefix}]\n\n{block['content']}",
                    "block":   block,
                })
            else:
                if len(current_text) + len(block["content"]) > self.MAX_CHUNK_SIZE and current_text.strip():
                    results.append({
                        "content": f"[섹션: {header_prefix}]\n\n{current_text.strip()}",
                        "block":   last_text_block,
                    })
                    current_text = block["content"] + "\n\n"
                else:
                    current_text += block["content"] + "\n\n"
                last_text_block = block

        if current_text.strip():
            results.append({
                "content": f"[섹션: {header_prefix}]\n\n{current_text.strip()}",
                "block":   last_text_block,
            })

        return results