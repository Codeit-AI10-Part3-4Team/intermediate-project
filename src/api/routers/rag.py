# src/api/routers/rag.py

from fastapi import APIRouter, Depends
from rag_core.interfaces import Orchestrator
from api.schemas import RagRequest, RagResponse
from api.dependencies import get_orchestrator

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("", response_model=RagResponse)
def query_rag(
    req: RagRequest, orchestrator: Orchestrator = Depends(get_orchestrator)
) -> RagResponse:
    # 요청 검증(스키마) -> rag_core 호출 -> 응답 반환, 비즈니스 로직 없음
    return orchestrator.run(query=req.query, top_k=req.top_k)
