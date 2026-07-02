# frontend — Streamlit 웹 UI

RFP RAG 서비스의 웹 프론트엔드입니다. FastAPI 백엔드(`src/api`)에 **HTTP로만** 요청하며,
`rag_core`/`api` 패키지를 import하지 않습니다 (백엔드 목업↔실제 전환 시 프론트 수정 불필요).

## 구성

- `app.py` — 엔트리포인트 (`st.navigation`으로 페이지 등록)
- `views/rag_query.py` — 질의 페이지 (`POST /rag`)
- `views/upload_check.py` — 업로드 적합성 검사 페이지 (`POST /upload`)
- `api_client.py` — 백엔드 HTTP 클라이언트 (httpx, 에러 → 사용자 메시지 변환)
- `.streamlit/config.toml` — 서버 설정 (port 8501, 업로드 20MB 제한)

## 설치 / 실행

```bash
pip install -e ".[frontend]"

# 1) 백엔드 실행 (별도 터미널, 목업 모드 기본)
uvicorn api.main:app --reload

# 2) 프론트엔드 실행 — 반드시 frontend/ 에서 (.streamlit/config.toml 적용 범위)
cd frontend
streamlit run app.py
```

접속: http://localhost:8501

## 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `RAG_API_BASE_URL` | `http://127.0.0.1:8000` | 백엔드 API 주소. GCP VM에서는 8000이 JupyterHub 점유라 `http://127.0.0.1:8080` 등으로 지정 |
| `RAG_API_TIMEOUT_SECONDS` | `60` | API 응답 대기 한도 (LLM 생성이 느릴 수 있어 여유 있게) |

## GCP VM 배포 메모

- 외부에는 **Streamlit 포트만 개방**하고, FastAPI는 `127.0.0.1`(loopback)에 바인딩합니다
  (Streamlit이 서버 사이드에서 API를 호출하므로 CORS·API 포트 개방 불필요).
- VM 포트: 8000·8001·8081(JupyterHub), 11434(Ollama)는 예약. 팀 합의로
  **API 8090(loopback) / FE 8501**을 사용합니다. 상세는 `deploy/systemd/rfp-*.service` 참고:
  `python -m uvicorn api.main:app --host 127.0.0.1 --port 8090`
  + `RAG_API_BASE_URL=http://127.0.0.1:8090 streamlit run app.py`
