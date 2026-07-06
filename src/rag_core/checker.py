from __future__ import annotations

import logging

from rag_core.orchestration.orchestrator import LangGraphOrchestrator
from rag_core.parsing import RfpParser
from rag_core.schemas import Chunk, RetrievedChunk, SuitabilityResult

logger = logging.getLogger(__name__)


class RfpSuitabilityChecker:
    def __init__(self, orchestrator: LangGraphOrchestrator, top_k: int = 15) -> None:
        self._orchestrator = orchestrator
        self._parser = RfpParser()
        self._top_k = top_k

    def check(self, file_path: str, company_info: str | None = None) -> SuitabilityResult:
        logger.info("[Checker] 파싱 시작: %s", file_path)
        doc = self._parser.parse(file_path)
        meta = doc.metadata or {}
        biz_name = meta.get("사업명", "")
        org_name = meta.get("발주기관", "")
        query = (f"{biz_name} {org_name} 입찰 적합도 분석").strip() or "입찰 적합도 분석"

        resp = self._orchestrator.run(query=query, top_k=self._top_k, company_info=company_info)

        bid = resp.usage.get("bid_analysis", {})
        total_score = bid.get("total_score", 0)
        grade = bid.get("grade", "🟡검토필요")
        risks = bid.get("risks", [])
        recommendation = bid.get("recommendation", resp.answer)
        items = bid.get("items", [])

        score_normalized = min(max(total_score / 100.0, 0.0), 1.0)
        is_suitable = total_score >= 60

        reasons: list[str] = []
        for item in items:
            name = item.get("name", "")
            tag = item.get("tag", "")
            reason = item.get("reason", "")
            if name and reason:
                reasons.append(f"{name} ({tag}): {reason}")
        for risk in risks:
            reasons.append(f"⚠️ {risk}")
        if recommendation:
            reasons.append(f"권고: {recommendation}")

        sources = [
            RetrievedChunk(
                chunk=Chunk(
                    chunk_id=s.chunk.chunk_id,
                    doc_id=s.chunk.doc_id,
                    text=s.chunk.text,
                    metadata=s.chunk.metadata,
                ),
                score=s.score,
            )
            for s in resp.sources[:5]
        ]

        return SuitabilityResult(
            is_suitable=is_suitable,
            score=round(score_normalized, 4),
            reasons=reasons,
            sources=sources,
            usage={
                "grade": grade,
                "total_score": total_score,
                "doc_id": doc.doc_id,
                "query": query,
            },
        )
