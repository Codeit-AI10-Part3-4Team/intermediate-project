# scripts/

## 역할
저장소 운영(GitHub 설정 등)을 자동화하는 일회성/반복 실행 스크립트를 보관합니다.
애플리케이션 런타임 코드가 아니라 **레포 셋업·유지보수용 도구**입니다.

## 스크립트 목록

### `setup-github.sh` — 레포 하드닝 (브랜치 보호 + Merge 전략 + 라벨)
`main` 브랜치 보호 규칙, Merge 전략, 라벨을 한 번에 적용합니다.

- 적용 내용
  - `main` 브랜치 보호: 직접 push 금지, PR 필수, 승인 1개 이상, 상태검사(`check`, 노트북 CI) 통과, force push/삭제 금지, linear history
  - Merge 전략: **Squash merge만 허용** + 머지 후 head 브랜치 자동 삭제
  - 라벨: `apply-labels.sh`를 호출해 일괄 생성
- 사전조건: `gh auth login` (저장소 **admin** 권한)
- 사용법
  ```bash
  bash scripts/setup-github.sh                 # 기본 레포(Codeit-AI10-Part3-4Team/intermediate-project)
  bash scripts/setup-github.sh OWNER/REPO      # 다른 레포 지정
  ```
- 주의: 비공개(private) 조직 레포에서는 일부 브랜치 보호 API에 유료 플랜이 필요할 수 있습니다.
  Secret scanning / Push protection은 API 적용이 제한적이라 **Settings > Code security에서 수동 활성화**하세요.

### `apply-labels.sh` — 라벨만 생성/갱신
`.github/labels.yml` 정의를 레포 라벨로 적용합니다(있으면 갱신, 없으면 생성).

- 사전조건: `gh auth login`, `yq` 설치 (`pip install yq` 또는 `brew install yq`)
- 사용법
  ```bash
  bash scripts/apply-labels.sh                 # 기본 레포
  bash scripts/apply-labels.sh OWNER/REPO      # 다른 레포 지정
  ```
- 라벨 정의는 [`.github/labels.yml`](../.github/labels.yml)에서 관리합니다(PR 템플릿의 '변경 유형'과 일치).

### 빌드 / 개발 환경 스크립트 (예정)
패키징·의존성 설치·환경 구성용 스크립트를 추가할 자리입니다. 추가 시 아래 틀로 기록하세요.

| 스크립트 | 용도 | 사전조건 | 사용법 |
|----------|------|----------|--------|
| `setup-env.sh` *(예정)* | 가상환경 생성 + 의존성 설치 | Python 3.12 | `bash scripts/setup-env.sh` |
| `run-tests.sh` *(예정)* | 린트 + 단위 테스트 실행 | 의존성 설치 완료 | `bash scripts/run-tests.sh` |

> 의존성 매니페스트(`pyproject.toml`/`requirements.txt`)가 아직 없습니다. 매니페스트 확정 후
> 위 스크립트를 실제로 추가하고, *(예정)* 표시를 지운 뒤 운영 스크립트와 동일한 형식으로 문서화하세요.

## 실행 순서 (신규 레포 셋업 시)
1. `gh auth login` (admin 권한)
2. `bash scripts/setup-github.sh` — 보호 규칙 + Merge 전략 + 라벨이 한 번에 적용됨
   (라벨만 다시 맞추고 싶을 때 `apply-labels.sh`를 단독 실행)

## 코딩 에이전트 참고
- 이 폴더의 스크립트는 **GitHub 상태를 변경**합니다(브랜치 보호, 라벨). 실행 전 대상 레포(`OWNER/REPO` 인자)를 반드시 확인하세요.
- 새 운영 스크립트를 추가하면 이 README의 "스크립트 목록"에 용도·사전조건·사용법을 함께 기록합니다.
- 설정 값(라벨, 보호 규칙)을 바꿀 때는 가능하면 스크립트에 하드코딩하지 말고 `.github/labels.yml`처럼 **선언적 파일로 분리**해 스크립트는 적용만 담당하게 하세요.
