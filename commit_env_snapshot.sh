#!/usr/bin/env bash
#
# commit_env_snapshot.sh
# backup_env.sh 가 만든 env 스냅샷(deploy/)을 backup_<날짜> 브랜치로 커밋·푸시하고
# 원래 작업 브랜치로 복귀한다. 사용자별 클론 경로에 무관하게 동작한다($HOME 가정 없음).
#
# 사용:  bash commit_env_snapshot.sh
#
set -euo pipefail

# 진단 개선: repo 루트로 이동 ($HOME 가정 제거 — 사용자마다 클론 경로가 다름)
cd "$(git rev-parse --show-toplevel)"

ORIG="$(git branch --show-current)"
[ -n "$ORIG" ] || { echo "오류: detached HEAD 상태입니다. 브랜치 위에서 실행하세요."; exit 1; }

DATE="$(date +%Y%m%d)"
BR="backup_${DATE}"

# 가드: 같은 날짜 브랜치가 이미 있으면 중단(같은 날 재실행 시 충돌 방지)
if git show-ref --verify --quiet "refs/heads/${BR}"; then
  echo "오류: 로컬에 '${BR}' 가 이미 있습니다. 삭제(git branch -D ${BR})하거나 접미사를 쓰세요."; exit 1
fi
[ -d deploy ] || { echo "오류: deploy/ 가 없습니다. backup_env.sh 를 먼저 실행했나요?"; exit 1; }
git remote get-url origin >/dev/null 2>&1 || { echo "오류: origin 원격이 없습니다."; exit 1; }

echo "원래 브랜치=${ORIG} · 백업 브랜치=${BR}"

# 중단 시 복구 안내 (side-effect 시작 이후부터만 적용 — 위의 사전 가드는 자체 메시지로 처리)
on_error() {
  echo "" >&2
  echo "[중단] 스냅샷 처리 중 오류로 멈췄습니다. 아래로 상태 확인·복구하세요:" >&2
  echo "  · 현재 브랜치 : $(git branch --show-current 2>/dev/null || echo '?')" >&2
  echo "  · 작업 복원   : git stash list | grep 'wip-${BR}'  → 있으면  git switch ${ORIG} && git stash pop" >&2
  [ -d "${TMP:-/nonexistent}" ] && echo "  · deploy 스냅샷 임시본 : ${TMP}" >&2
  echo "  · 원래 브랜치 복귀 : git switch ${ORIG}" >&2
}
trap on_error ERR

# (1) 현재 브랜치 저장 → $ORIG (위에서 완료)

# (2) deploy/ 를 제외한 나머지 작업 내용 stash (추적·미추적 모두). 없으면 stash 를 만들지 않음.
git stash push -u -m "wip-${BR}" -- . ':(exclude)deploy' || true
STASHED="$(git stash list | grep -c "wip-${BR}" || true)"

# deploy/ 스냅샷을 repo 밖에 보존 → 브랜치 전환·pull 에 영향받지 않는다.
# (deploy/ 는 '생성된 스냅샷'이라 3-way 병합이 아니라 통째 교체가 올바른 의미)
TMP="$(mktemp -d)"
cp -a deploy/. "$TMP"/
[ -n "$(ls -A "$TMP")" ] || { echo "오류: 스냅샷 임시 복사 실패"; rm -rf "$TMP"; exit 1; }

# 작업트리의 deploy/ 를 HEAD 상태로 되돌려 전환을 깨끗하게(스냅샷은 $TMP 에 안전)
git checkout HEAD -- deploy
git clean -fdq deploy

# (3) 로컬 main 을 origin/main 으로 fast-forward (ff 불가 시 ff-only 가 명확히 멈춰 사고 방지)
# 로컬 main 이 없을 수 있다(막 클론한 협업자) → origin/main 추적 브랜치로 생성
git switch -q main 2>/dev/null || git switch -q -c main --track origin/main
git pull -q --ff-only origin main

# (4) main 기준으로 backup 브랜치 생성·이동
git switch -q -c "$BR"

# (5) 보존본으로 deploy/ 전체 교체 후 commit & push (add/수정/삭제 모두 반영)
rm -rf deploy && mkdir deploy && cp -a "$TMP"/. deploy/
git add -A deploy
git commit -qm "chore: env snapshot ${DATE}"
git push -q -u origin "$BR"

# (6) 원래 브랜치로 복귀
git switch -q "$ORIG"

# (7) stash 에 있던 작업 내용 복원 (2단계에서 실제로 만들어진 경우만)
if [ "${STASHED:-0}" -ge 1 ]; then
  git stash pop
fi

rm -rf "$TMP"
echo "완료: '${BR}' 푸시 · '${ORIG}' 복귀 · stash복원=${STASHED}"
