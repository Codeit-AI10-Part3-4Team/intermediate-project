# src/api/routers/upload.py
# 업로드 문서의 RFP 적합성 검사 (docs/architecture.md §4).
# 라우터는 web 관심사만: 검증 → transient 임시 저장 → rag_core 판정 호출 → 폐기.
# 업로드 문서는 영속 저장하지 않으며, 코퍼스 DB도 갱신하지 않는다.

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from api.dependencies import get_suitability_checker
from api.schemas import SuitabilityResult
from rag_core.interfaces import SuitabilityChecker
from rag_core.parsing import ParsingError, UnsupportedFormatError

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_EXTENSIONS = {".hwp", ".pdf"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB — 필요 시 Settings로 이전 가능
_READ_CHUNK = 1024 * 1024


@router.post("", response_model=SuitabilityResult)
async def check_upload(
    file: UploadFile,
    checker: SuitabilityChecker = Depends(get_suitability_checker),
) -> SuitabilityResult:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"지원하지 않는 형식: {ext or '(없음)'} (지원: hwp, pdf)",
        )

    # transient: 임시 파일로 받아 검사에 넘기고, 끝나면 반드시 삭제(영속 저장 없음).
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
            size = 0
            while chunk := await file.read(_READ_CHUNK):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB)",
                    )
                tmp.write(chunk)

        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="빈 파일입니다."
            )

        # 도메인 판정(parse→embed→비교→llm)은 checker 내부. 파싱 실패는 HTTP로 변환.
        try:
            return checker.check(tmp_path)
        except UnsupportedFormatError as e:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(e)) from e
        except ParsingError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
