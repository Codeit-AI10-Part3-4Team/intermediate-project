#!/usr/bin/env bash
# VM 배포 스크립트 — origin/main을 서비스 체크아웃에 반영하고 rfp-* 서비스를 재시작한다.
# 절차 설명·전제조건·트러블슈팅은 deploy/README.md(러너북) 참고.
#
# 사용법 (VM의 서비스 계정으로, 저장소 안 어디서든):
#   scripts/deploy_vm.sh
#   DEPLOY_EXTRAS=retrieval scripts/deploy_vm.sh   # 의존성 재설치에 extra 포함
#
# 하는 일:
#   1. main 브랜치·clean 작업트리 확인 → fetch → origin/main을 ff-only로 반영
#   2. pyproject.toml 변경 시: 서비스 venv에 pip install -e 재실행
#   3. deploy/systemd/*.service 변경 시: /etc/systemd/system 복사 + daemon-reload (sudo)
#   4. rfp-api 재시작, frontend/ 변경 시 rfp-frontend도 재시작 (sudo)
#   5. 스모크: GET /openapi.json 대기 → POST /rag 200 확인
set -euo pipefail

SERVICE_PYTHON="${SERVICE_PYTHON:-$HOME/ai/bin/python}"
API_PORT="${API_PORT:-8090}"

cd "$(git rev-parse --show-toplevel)"

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

if grep -q "^deploy/systemd/" <<<"$changed"; then
    echo "[deploy] systemd 유닛 변경 → /etc/systemd/system 복사 + daemon-reload"
    sudo cp deploy/systemd/rfp-*.service /etc/systemd/system/
    sudo systemctl daemon-reload
fi

echo "[deploy] rfp-api 재시작"
sudo systemctl restart rfp-api
if grep -q "^frontend/" <<<"$changed"; then
    echo "[deploy] frontend/ 변경 → rfp-frontend 재시작"
    sudo systemctl restart rfp-frontend
fi

# 기동 대기: use_mock=false면 임베딩 모델 로드로 기동에 수십 초 걸릴 수 있다.
echo "[deploy] 기동 대기 (최대 120초)"
ready=0
for _ in $(seq 1 60); do
    if curl -sf -o /dev/null "127.0.0.1:${API_PORT}/openapi.json"; then
        ready=1
        break
    fi
    sleep 2
done
if [[ "$ready" != "1" ]]; then
    echo "[deploy] ❌ API가 기동하지 않습니다 — 'systemctl status rfp-api'와 로그를 확인하세요." >&2
    exit 1
fi

status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 180 \
    -X POST "127.0.0.1:${API_PORT}/rag" \
    -H 'Content-Type: application/json' -H 'X-Request-ID: deploy-smoke' \
    -d '{"query":"배포 스모크 테스트","top_k":1}')
if [[ "$status" != "200" ]]; then
    echo "[deploy] ❌ POST /rag 스모크 실패 (HTTP $status) — 러너북의 트러블슈팅 참고." >&2
    exit 1
fi

echo "[deploy] ✅ 완료: $(git log --oneline -1 | head -c 80) / POST /rag -> $status"
