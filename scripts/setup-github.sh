#!/usr/bin/env bash
# GitHub 레포 하드닝: 브랜치 보호 + Merge 전략 + 라벨.
# 사전조건: gh auth login (admin 권한 필요)
#   주의: 브랜치 보호 API의 일부는 비공개(private) 조직 레포에서 유료 플랜이 필요할 수 있습니다.
set -euo pipefail

REPO="${1:-Codeit-AI10-Part3-4Team/intermediate-project}"
SCRIPT_DIR="$(dirname "$0")"

echo "==> main 브랜치 보호 규칙 적용"
# 상태검사 context 'check' = notebook-check.yml 의 job id.
gh api -X PUT "repos/$REPO/branches/main/protection" \
  -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["check"] },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": true
}
JSON

echo "==> Merge 전략: Squash 전용 + 머지 후 브랜치 자동 삭제"
gh repo edit "$REPO" \
  --enable-squash-merge=true \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge=true

echo "==> 라벨 적용"
bash "$SCRIPT_DIR/apply-labels.sh" "$REPO"

echo "완료. (Secret scanning/Push protection 은 Settings > Code security 에서 활성화하세요.)"
