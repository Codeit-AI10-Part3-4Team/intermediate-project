#!/usr/bin/env bash
# VM 배포 스크립트 — origin/main을 서비스 체크아웃에 반영하고 rfp-* 서비스를 재시작한다.
# 절차 설명·전제조건·트러블슈팅은 deploy/README.md(러너북) 참고.
#
# 사용법 (VM의 서비스 계정으로, 저장소 안 어디서든):
#   scripts/deploy_vm.sh
#   scripts/deploy_vm.sh --history                 # 배포 이력(성공/실패/롤백)과 last_good 출력
#   DEPLOY_EXTRAS=retrieval scripts/deploy_vm.sh   # 의존성 재설치에 extra 포함
#
# 하는 일:
#   1. main 브랜치·clean 작업트리 확인 → fetch → origin/main을 ff-only로 반영
#   2. pyproject.toml 변경 시: 서비스 venv에 pip install -e 재실행
#   3. deploy/systemd/rfp-*.service가 /etc의 사본과 다르면: 복사 + daemon-reload (sudo)
#   4. rfp-api 재시작, frontend/ 변경 시 rfp-frontend도 재시작 (sudo)
#   5. 스모크: GET /openapi.json 대기 → POST /rag 200 확인
#   6. 결과를 상태 디렉토리에 기록 — 성공 시 last_good 갱신,
#      연속 FAIL_STREAK_LIMIT(기본 3)회 실패 시 last_good으로 자동 롤백 후 스모크 재검증.
#      status.json은 프론트엔드 배너(frontend/ui.py render_status_banner)가 읽는다.
#
# 자동 롤백의 범위: 코드 + systemd 유닛만. 데이터(vector_db)·.env는 되돌리지 않는다
# (pyproject가 다르면 pip install -e 재실행은 함). 롤백은 자동, 재배포(롤포워드)는
# 원인 수정 후 사람이 수행한다.
set -euo pipefail

# root로 통째로 돌리면 스크립트 안의 git이 .git을 root 소유로 오염시킨다.
# 서비스 계정으로 실행하고, 필요한 곳(systemctl/cp)만 내부에서 sudo를 쓴다.
if [[ ${EUID} -eq 0 ]]; then
    echo "[deploy] 중단: root(sudo)로 실행하지 마세요 — 'bash scripts/deploy_vm.sh'로 실행하면" >&2
    echo "[deploy] 필요한 단계에서만 sudo 비밀번호를 묻습니다." >&2
    exit 1
fi

SERVICE_PYTHON="${SERVICE_PYTHON:-$HOME/ai/bin/python}"
API_PORT="${API_PORT:-8090}"
# use_mock=false 첫 기동은 임베딩 모델 다운로드+BM25 빌드로 수 분 걸릴 수 있다.
STARTUP_WAIT_SECS="${STARTUP_WAIT_SECS:-300}"
# 배포 상태(이력·last_good·연속 실패 카운터·status.json)는 저장소 밖에 둔다 —
# 롤백으로 체크아웃이 과거로 돌아가도 이력은 살아남아야 한다.
STATE_DIR="${DEPLOY_STATE_DIR:-$HOME/.local/state/rfp-deploy}"
FAIL_STREAK_LIMIT="${FAIL_STREAK_LIMIT:-3}"

HISTORY_FILE="$STATE_DIR/history.log"
LAST_GOOD_FILE="$STATE_DIR/last_good"
STREAK_FILE="$STATE_DIR/fail_streak"
STATUS_FILE="$STATE_DIR/status.json" # 경로 계약: frontend/ui.py 기본값과 일치

mkdir -p "$STATE_DIR"

if [[ "${1:-}" == "--history" ]]; then
    if [[ -s "$HISTORY_FILE" ]]; then
        cat "$HISTORY_FILE"
    else
        echo "(이력 없음)"
    fi
    echo "--"
    echo "last_good: $(cat "$LAST_GOOD_FILE" 2>/dev/null || echo '(없음)')"
    echo "연속 실패: $(cat "$STREAK_FILE" 2>/dev/null || echo 0)"
    exit 0
fi

log_history() { # $1=결과 $2=sha $3=비고
    printf '%s | %-12s | %s | %s\n' "$(date -Is)" "$1" "$2" "${3:-}" >>"$HISTORY_FILE"
}

write_status() { # $1=state $2=message  (메시지에 따옴표 금지 — JSON을 직접 조립한다)
    printf '{"state": "%s", "sha": "%s", "message": "%s", "at": "%s"}\n' \
        "$1" "$(git rev-parse --short HEAD)" "$2" "$(date -Is)" >"$STATUS_FILE"
}

sync_units() {
    local updated=0 unit target
    # 유닛 동기화는 git diff가 아니라 /etc 사본과의 실제 내용 비교로 판단한다 —
    # 수동 pull 후 실행해도(diff가 비어도) 유닛 변경을 놓치지 않는다.
    for unit in deploy/systemd/rfp-*.service; do
        target="/etc/systemd/system/$(basename "$unit")"
        if ! cmp -s "$unit" "$target" 2>/dev/null; then
            echo "[deploy] 유닛 갱신: $(basename "$unit") → /etc/systemd/system/"
            sudo cp "$unit" "$target"
            updated=1
        fi
    done
    if [[ "$updated" == "1" ]]; then
        sudo systemctl daemon-reload
    fi
}

restart_services() { # $1=frontend도 재시작하면 1
    # StartLimit로 멈춘(crash-loop 차단) 유닛은 reset-failed 없이는 재시작이 거부된다.
    sudo systemctl reset-failed rfp-api rfp-frontend 2>/dev/null || true
    echo "[deploy] rfp-api 재시작"
    sudo systemctl restart rfp-api
    if [[ "${1:-}" == "1" ]]; then
        echo "[deploy] rfp-frontend 재시작"
        sudo systemctl restart rfp-frontend
    fi
}

wait_api() {
    echo "[deploy] 기동 대기 (최대 ${STARTUP_WAIT_SECS}초 — 첫 기동은 모델 로드로 오래 걸림)"
    local _i
    for _i in $(seq 1 $((STARTUP_WAIT_SECS / 5))); do
        if curl -sf -o /dev/null "127.0.0.1:${API_PORT}/openapi.json"; then
            return 0
        fi
        sleep 5
    done
    echo "[deploy] ${STARTUP_WAIT_SECS}초 내 기동하지 않았습니다 — 'sudo journalctl -u rfp-api -n 50'으로" >&2
    echo "[deploy] 실패 원인을 확인하세요 (active인데 느린 것이면 모델 로드 중일 수 있음)." >&2
    return 1
}

smoke_rag() {
    local status
    status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 180 \
        -X POST "127.0.0.1:${API_PORT}/rag" \
        -H 'Content-Type: application/json' -H 'X-Request-ID: deploy-smoke' \
        -d '{"query":"배포 스모크 테스트","top_k":1}')
    if [[ "$status" != "200" ]]; then
        echo "[deploy] POST /rag 스모크 실패 (HTTP $status) — 러너북의 트러블슈팅 참고." >&2
        return 1
    fi
}

rollback_to_last_good() {
    local target
    target=$(cat "$LAST_GOOD_FILE" 2>/dev/null || true)
    if [[ -z "$target" ]]; then
        echo "[deploy] ⚠️ last_good 기록이 없어 자동 롤백할 수 없습니다 — 러너북의 수동 복구 절차로." >&2
        write_status degraded "배포 연속 실패 — 자동 롤백 불가(성공 이력 없음)"
        return
    fi
    if [[ "$(git rev-parse HEAD)" == "$target" ]]; then
        echo "[deploy] ⚠️ 현재 HEAD가 이미 last_good입니다 — 코드가 아니라 환경/데이터 문제" >&2
        echo "[deploy]    (예: vector_db 권한, .env, Ollama)입니다. 러너북 트러블슈팅 참고." >&2
        write_status degraded "배포 연속 실패 — 코드 외 원인, 점검 필요"
        return
    fi

    echo "[deploy] ⏪ 연속 ${FAIL_STREAK_LIMIT}회 실패 → last_good($(git rev-parse --short "$target"))으로 롤백합니다."
    local pyproject_changed=0
    if ! git diff --quiet HEAD "$target" -- pyproject.toml; then
        pyproject_changed=1
    fi

    git reset --hard "$target"
    if [[ "$pyproject_changed" == "1" ]]; then
        echo "[deploy] pyproject.toml 차이 → pip install -e 재실행"
        "$SERVICE_PYTHON" -m pip install -e ".${DEPLOY_EXTRAS:+[$DEPLOY_EXTRAS]}"
    fi
    sync_units
    # 롤백은 안전 우선: frontend 변경 여부와 무관하게 양쪽 서비스를 모두 재시작한다.
    restart_services 1
    if wait_api && smoke_rag; then
        echo 0 >"$STREAK_FILE"
        log_history "ROLLBACK_OK" "$(git rev-parse --short HEAD)" "서비스 복구됨"
        write_status rolled_back "최신 배포 연속 실패 — 이전 안정 버전으로 운영 중"
        echo "[deploy] ✅ 롤백 완료 — 서비스는 last_good에서 운영 중입니다. 원인 수정 후 재배포하세요."
    else
        log_history "ROLLBACK_FAIL" "$(git rev-parse --short HEAD)" "롤백 후에도 스모크 실패"
        write_status down "서비스 복구 실패 — 점검 중"
        echo "[deploy] ❌ 롤백 후에도 기동/스모크에 실패했습니다 — 러너북 수동 복구 절차로 진행하세요." >&2
    fi
}

deploy_failed() { # $1=사유 — 프리플라이트 이후의 모든 실패가 여기로 온다
    trap - ERR
    set +e
    local sha streak
    sha=$(git rev-parse --short HEAD)
    streak=$(($(cat "$STREAK_FILE" 2>/dev/null || echo 0) + 1))
    echo "$streak" >"$STREAK_FILE"
    log_history "FAIL" "$sha" "$1 (연속 ${streak}회)"
    echo "[deploy] ❌ 배포 실패: $1 — 연속 ${streak}회" >&2
    if ((streak >= FAIL_STREAK_LIMIT)); then
        rollback_to_last_good
    else
        write_status degraded "배포 실패 연속 ${streak}회 — ${FAIL_STREAK_LIMIT}회 시 자동 롤백"
        echo "[deploy] 연속 ${FAIL_STREAK_LIMIT}회 실패 시 last_good으로 자동 롤백합니다." >&2
    fi
    exit 1
}

cd "$(git rev-parse --show-toplevel)"

# ---------- 프리플라이트 (여기서의 중단은 배포 "시도"로 집계하지 않는다) ----------
branch=$(git branch --show-current)
if [[ "$branch" != "main" ]]; then
    echo "[deploy] 중단: 현재 브랜치가 main이 아닙니다 ($branch)." >&2
    echo "[deploy] 서비스 체크아웃은 main을 추종합니다 — 'git switch main' 후 재실행하세요." >&2
    exit 1
fi

if [[ -n "$(git status --porcelain -uno)" ]]; then
    echo "[deploy] 중단: 작업트리가 clean하지 않습니다. 커밋/스태시 후 재실행하세요." >&2
    git status --short -uno >&2
    exit 1
fi

old_head=$(git rev-parse HEAD)
git fetch origin
# 로컬 커밋이 있으면 여기서 실패한다 — VM에서는 커밋하지 않는 것이 원칙(러너북 참고).
git merge --ff-only origin/main
new_head=$(git rev-parse HEAD)

# ---------- 배포 단계 (실패는 이력 집계 + 연속 실패 시 자동 롤백) ----------
trap 'deploy_failed "예상치 못한 오류 (line $LINENO)"' ERR

changed=""
if [[ "$old_head" != "$new_head" ]]; then
    changed=$(git diff --name-only "$old_head" "$new_head")
else
    echo "[deploy] 이미 최신입니다 — 재시작·스모크만 진행합니다."
fi

if grep -q "^pyproject.toml$" <<<"$changed"; then
    extras="${DEPLOY_EXTRAS:-}"
    echo "[deploy] pyproject.toml 변경 → pip install -e 재실행 (extras: ${extras:-없음})"
    "$SERVICE_PYTHON" -m pip install -e ".${extras:+[$extras]}"
fi

sync_units

frontend_restart=0
if grep -q "^frontend/" <<<"$changed"; then
    frontend_restart=1
fi
restart_services "$frontend_restart"

if ! wait_api; then
    deploy_failed "기동 시간 초과 (${STARTUP_WAIT_SECS}초)"
fi
if ! smoke_rag; then
    deploy_failed "POST /rag 스모크 실패"
fi

# ---------- 성공 ----------
trap - ERR
echo 0 >"$STREAK_FILE"
git rev-parse HEAD >"$LAST_GOOD_FILE"
log_history "OK" "$(git rev-parse --short HEAD)" "$(git log --format=%s -1 | head -c 60)"
write_status ok "정상 운영 중"
echo "[deploy] ✅ 완료: $(git log --oneline -1 | head -c 80) / POST /rag -> 200"
