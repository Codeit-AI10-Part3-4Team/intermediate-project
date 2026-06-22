#!/usr/bin/env bash
# .github/labels.yml 의 라벨을 레포에 생성/갱신한다.
# 사전조건: gh auth login (repo 권한)
set -euo pipefail

REPO="${1:-Codeit-AI10-Part3-4Team/intermediate-project}"
LABELS_FILE="$(dirname "$0")/../.github/labels.yml"

# 의존성: yq (없으면 안내). 없으면 .github/labels.yml 참고해 수동 생성.
if ! command -v yq >/dev/null 2>&1; then
  echo "yq 가 필요합니다. (brew install yq / pip install yq)" >&2
  exit 1
fi

count=$(yq '. | length' "$LABELS_FILE")
for i in $(seq 0 $((count - 1))); do
  name=$(yq -r ".[$i].name" "$LABELS_FILE")
  color=$(yq -r ".[$i].color" "$LABELS_FILE")
  desc=$(yq -r ".[$i].description" "$LABELS_FILE")
  # 이미 있으면 갱신(--force), 없으면 생성
  gh label create "$name" --color "$color" --description "$desc" --repo "$REPO" --force
done

echo "라벨 적용 완료: $REPO"
