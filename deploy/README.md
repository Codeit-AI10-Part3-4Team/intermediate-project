# deploy/ — VM 운영 러너북

GCP VM에서 상시 구동 중인 서비스의 **배포·모드 전환·트러블슈팅 절차**입니다.
이 디렉토리의 나머지 파일(systemd 유닛, venv freeze, apt 목록)은 VM 환경 재현 자산입니다.

## 서비스 구성

| systemd 유닛 | 포트 | 역할 | 코드 위치 |
| --- | --- | --- | --- |
| `rfp-api` | **127.0.0.1:8090** (loopback 전용) | FastAPI 백엔드 | `~/intermediate-project` (editable install) |
| `rfp-frontend` | **0.0.0.0:8501** (유일한 외부 개방) | Streamlit 웹 UI | 〃 (`frontend/`) |
| `ollama` | 127.0.0.1:11434 | LLM 서버 (exaone3.5:7.8b) | — |
| `jupyterhub` | 8000·8001·8081 | 팀 개발 환경 + Swagger 프록시 통로 | — |

그 외 포트: 8080·8502는 PM 실험용 예약. Swagger 접근은 [src/api/README.md](../src/api/README.md) 참고.

## 일상 배포: PR 머지 → 서버 반영

**원칙**: VM 체크아웃은 **main만 추종**하고, VM에서 직접 커밋하지 않습니다.
머지한 사람이 반영합니다 — JupyterHub 터미널(서비스 계정)에서:

```bash
cd ~/intermediate-project
scripts/deploy_vm.sh
```

스크립트가 변경 내용에 따라 필요한 단계를 알아서 수행합니다:

| 변경 내용 | 필요한 처리 | 스크립트 동작 |
| --- | --- | --- |
| `src/` 코드만 | pull + 재시작 (editable이라 재설치 불필요) | 항상 수행 |
| `pyproject.toml` (의존성) | 서비스 venv에 `pip install -e` 재실행 | 변경 감지 시 자동. extra가 필요하면 `DEPLOY_EXTRAS=retrieval scripts/deploy_vm.sh` |
| `deploy/systemd/*.service` | `/etc/systemd/system` 복사 + `daemon-reload` | 변경 감지 시 자동 (sudo) |
| `frontend/` | `rfp-frontend`도 재시작 | 변경 감지 시 자동 |

마지막에 `POST /rag` 스모크까지 통과해야 성공으로 끝납니다.
수동으로 할 때의 최소 절차: clean 확인 → `git fetch origin && git merge --ff-only origin/main` →
(해당 시) pip/유닛 갱신 → `sudo systemctl restart rfp-api` → 스모크.

## 모드 전환: Mock ↔ 실제 파이프라인 (`use_mock`)

`APP_USE_MOCK=false` + **`rfp-api` 재시작**으로 LangGraph Orchestrator가 배선됩니다.
설정은 `api/lifespan.py`가 **기동 시 1회만** 읽으므로 재시작 없이는 절대 반영되지 않습니다
(핫리로드 없음). `.env` 위치는 서비스의 WorkingDirectory인 `~/intermediate-project/.env`
(git 미추적)입니다.

```bash
echo "APP_USE_MOCK=false" >> ~/intermediate-project/.env
sudo systemctl restart rfp-api
```

> ⚠️ **`.env`로 전달되는 것은 `APP_` 접두어의 Settings 필드뿐입니다** (pydantic-settings).
> `CHROMA_DIR`·`OLLAMA_BASE_URL`은 코드가 `os.getenv()`로 직접 읽으므로 `.env`에 적어도
> 효과가 없습니다 — 기본값(`/data/vector_db/vector_db_v4`, `http://127.0.0.1:11434`)과 다르게
> 쓰려면 `rfp-api.service`에 `Environment=CHROMA_DIR=...` 줄을 추가하고 유닛을 재배포하세요.

### 전환 전 체크리스트

1. **의존성**: 서비스 venv에 retrieval 계열 + `langgraph`가 있어야 합니다.
   ⚠️ `langgraph`는 현재 `pyproject.toml` 어느 extra에도 선언돼 있지 않아 **수동 설치** 대상입니다.
   ```bash
   ~/ai/bin/python -c "import langgraph, chromadb, sentence_transformers; print('ok')"
   # 실패 시: ~/ai/bin/python -m pip install -e ".[retrieval]" langgraph
   ```
2. **벡터 DB**: Chroma 경로 존재 확인 — `ls /data/vector_db/vector_db_v4`
3. **Ollama**: `systemctl is-active ollama` + `ollama list`에 `exaone3.5:7.8b`
4. `/upload`(적합성 검사)는 이 전환과 무관하게 **여전히 Mock**입니다.

### 확인과 롤백

- 확인: Swagger에서 `POST /rag` 실행 — `answer`가 `"(mock)"`으로 시작하면 아직 Mock 경로입니다.
- 실경로 첫 기동은 임베딩 모델 로드로 **수십 초** 걸릴 수 있습니다 (스크립트는 120초까지 대기).
- 롤백: `.env`를 `APP_USE_MOCK=true`로 되돌리고 재시작 — 그게 전부입니다.

## 로그 / 트러블슈팅

**로그 위치**
- `sudo journalctl -u rfp-api -f` (sudo 필요)
- `/var/log/rfp/api.log` — sudo 없이 열람 가능 (요청 추적 로깅 PR 반영 이후)

**흔한 증상**

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| 기동 즉사 `ModuleNotFoundError` | systemd는 빈 환경으로 시작 — 공용 venv 빌림 배선 누락 | 유닛의 `Environment=PYTHONPATH=...` 확인 (rfp-api.service 주석 참고) |
| `merge --ff-only` 실패 | VM 체크아웃에 로컬 커밋/브랜치 이탈 | `git log origin/main..HEAD`로 확인 — VM 커밋은 원칙 위반, 브랜치로 빼서 push |
| 502/504 응답 | Ollama 미기동·타임아웃 (요청 추적 로깅 PR 이후 구분됨) | `systemctl status ollama`, `ollama list` |
| 기동이 오래 걸림 | `use_mock=false` 첫 기동의 임베딩 모델 로드 | 정상 — 120초까지 대기 |
| 포트 충돌 | 8000/8001/8081/8080/8502는 타 서비스 예약 | 위 포트 지도 준수 |

**서버 전체 복구**(디스크 스냅샷 수준)는 별도 문서: [`서버_복구_가이드.md`](../서버_복구_가이드.md)
