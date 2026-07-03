# src/api/logging_config.py
"""애플리케이션 로깅 설정 (조합 루트 전용).

rag_core는 모듈 로거(logging.getLogger(__name__))로 찍기만 하고 핸들러/포맷을
설정하지 않는다 — 설정은 api가 기동할 때 여기서 한 번만 한다 (의존성 규칙 유지).

모든 로그 라인에 현재 요청의 X-Request-ID가 붙는다 (RequestIdFilter).
APP_LOG_FILE이 설정되면 회전 파일 핸들러를 추가한다 — VM에서 sudo 없이
로그를 볼 수 있는 통로 (journalctl은 팀원 권한으로 접근 불가).
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from api.middleware import request_id_var

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"

_configured = False


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    # TestClient가 lifespan을 반복 실행해도 핸들러가 중복되지 않게 1회만 설정.
    global _configured
    if _configured:
        return

    formatter = logging.Formatter(_LOG_FORMAT)
    request_id_filter = RequestIdFilter()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        )

    root = logging.getLogger()
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(request_id_filter)
        root.addHandler(handler)
    root.setLevel(level.upper())

    # api.access가 request_id 포함 액세스 로그를 대신하므로 uvicorn 기본 라인은 줄인다.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _configured = True
