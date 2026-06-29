#!/usr/bin/env bash
# =============================================================================
# backup_env.sh — GCP VM 환경 설정 백업 스크립트
#
# 용도: JupyterHub/Ollama 기반 팀 개발 VM의 복구용 스냅샷을 생성한다.
# 실행: bash backup_env.sh [--dry-run]
#
# 출력 구조:
#   deploy/
#   ├── jupyterhub/jupyterhub_config.py   (API 키 값 마스킹)
#   ├── systemd/jupyterhub.service
#   ├── systemd/ollama.service            (존재 시)
#   ├── requirements.lock
#   ├── apt_packages.txt
#   ├── venv_freeze/
#   │   └── jhub-venv.txt                 (basename of JUPYTERHUB_VENV)
#   └── backup_meta.txt                   (백업 메타데이터)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 설정 (환경에 맞게 수정)
# ---------------------------------------------------------------------------
# 스크립트가 위치한 디렉토리를 기준으로 deploy 폴더 생성
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-$SCRIPT_DIR/deploy}"

JUPYTERHUB_CONFIG="/root/jupyterhub_config.py"
JUPYTERHUB_SERVICE="/etc/systemd/system/jupyterhub.service"
OLLAMA_SERVICE="/etc/systemd/system/ollama.service"
# requirements.lock 위치 — repo 루트에서 탐색(스크립트가 repo 어디에 있든 동작)
# 환경 변수로 재정의 가능: REQUIREMENTS_LOCK=/path/to/requirements.lock bash backup_env.sh
_REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_DIR")"
REQUIREMENTS_LOCK="${REQUIREMENTS_LOCK:-$_REPO_ROOT/requirements.lock}"
# JupyterHub 전용 venv 경로 (pip freeze 대상)
JUPYTERHUB_VENV="${JUPYTERHUB_VENV:-/opt/jhub-venv}"
# 추가로 freeze할 venv 경로 목록 (공백 구분, 없으면 빈 문자열)
# 예: EXTRA_VENVS="/opt/project/venv /home/ubuntu/myenv"
EXTRA_VENVS="${EXTRA_VENVS:-}"

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

# ---------------------------------------------------------------------------
# 유틸리티 함수
# ---------------------------------------------------------------------------
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
warn() { echo "[WARN] $*" >&2; }

run() {
    if $DRY_RUN; then
        echo "[DRY-RUN] $*"
    else
        "$@"
    fi
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || { warn "명령어 없음: $1 (스킵)"; return 1; }
}

# ---------------------------------------------------------------------------
# 디렉토리 초기화
# ---------------------------------------------------------------------------
init_dirs() {
    log "백업 디렉토리 초기화: $DEPLOY_DIR"
    run mkdir -p \
        "$DEPLOY_DIR/jupyterhub" \
        "$DEPLOY_DIR/systemd" \
        "$DEPLOY_DIR/venv_freeze"
}

# ---------------------------------------------------------------------------
# 1. JupyterHub 설정 파일 — API 키 값 마스킹
# ---------------------------------------------------------------------------
backup_jupyterhub_config() {
    log "JupyterHub 설정 백업..."

    if [[ ! -f "$JUPYTERHUB_CONFIG" ]]; then
        warn "파일 없음: $JUPYTERHUB_CONFIG"
        return
    fi

    local dest="$DEPLOY_DIR/jupyterhub/jupyterhub_config.py"

    if $DRY_RUN; then
        echo "[DRY-RUN] sed 마스킹 후 → $dest"
        return
    fi

    # 마스킹 규칙(값을 모두 "키를 입력하세요"로 통일 — 복구 가이드 grep과 호환):
    #   1) "sk-..." 형태 토큰 값
    #   2) keyword = "..." 할당 형태
    #   3) "NAME": "..." 딕셔너리 형태 — NAME에 KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL 포함 시
    #      (c.Spawner.environment 딕셔너리의 비-sk 값까지 마스킹)
    local mask_sed
    mask_sed="$(mktemp)"
    cat > "$mask_sed" <<'SED'
s/(["'])(sk-[A-Za-z0-9_-]+)\1/\1키를 입력하세요\1/g
s/(api[_-]?key|api[_-]?secret|token|password|secret|credential)[[:space:]]*=[[:space:]]*(["'])[^"']*\2/\1 = \2키를 입력하세요\2/gI
s/(["'][A-Za-z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Za-z0-9_]*["'][[:space:]]*:[[:space:]]*)(["'])[^"']*\3/\1\3키를 입력하세요\3/gI
SED
    sed -E -f "$mask_sed" "$JUPYTERHUB_CONFIG" > "$dest"
    rm -f "$mask_sed"

    # 마스킹 검증 게이트: 알려진 비밀 prefix가 남으면 유출 위험 → 백업 중단
    if grep -Eq '(sk-[A-Za-z0-9]|ghp_|gho_|hf_[A-Za-z0-9]|AKIA[0-9A-Z]|xox[baprs]-|-----BEGIN )' "$dest"; then
        warn "마스킹 후에도 비밀로 의심되는 값이 남아 있습니다: $dest"
        warn "  마스킹 규칙을 보강한 뒤 다시 실행하세요. 유출 방지를 위해 중단합니다."
        rm -f "$dest"
        exit 1
    fi

    log "  → $dest (API 키 값 마스킹 완료 · 검증 통과)"
}

# ---------------------------------------------------------------------------
# 2. systemd 서비스 파일
# ---------------------------------------------------------------------------
backup_systemd_services() {
    log "systemd 서비스 파일 백업..."

    local services=(
        "$JUPYTERHUB_SERVICE:jupyterhub.service"
        "$OLLAMA_SERVICE:ollama.service"
    )

    for entry in "${services[@]}"; do
        local src="${entry%%:*}"
        local name="${entry##*:}"

        if [[ ! -f "$src" ]]; then
            warn "서비스 파일 없음: $src (스킵)"
            continue
        fi

        run cp "$src" "$DEPLOY_DIR/systemd/$name"
        log "  → $DEPLOY_DIR/systemd/$name"
    done
}

# ---------------------------------------------------------------------------
# 4. requirements.lock
# ---------------------------------------------------------------------------
backup_requirements() {
    log "requirements.lock 백업..."

    # REQUIREMENTS_LOCK 경로를 realpath로 정규화해 심볼릭 링크도 처리
    local lock_path
    lock_path=$(realpath "$REQUIREMENTS_LOCK" 2>/dev/null || echo "$REQUIREMENTS_LOCK")

    if [[ ! -f "$lock_path" ]]; then
        warn "파일 없음: $lock_path"
        warn "  힌트: REQUIREMENTS_LOCK=/절대/경로/requirements.lock bash backup_env.sh"
        return
    fi

    run cp "$lock_path" "$DEPLOY_DIR/requirements.lock"
    log "  → $DEPLOY_DIR/requirements.lock (원본: $lock_path)"
}

# ---------------------------------------------------------------------------
# 5. 시스템 APT 패키지 목록
# ---------------------------------------------------------------------------
backup_apt_packages() {
    log "APT 패키지 목록 백업..."

    if ! require_cmd dpkg; then return; fi

    local dest="$DEPLOY_DIR/apt_packages.txt"

    if $DRY_RUN; then
        echo "[DRY-RUN] dpkg --get-selections → $dest"
        return
    fi

    # manually-installed 패키지만 (auto-installed 제외)
    comm -23 \
        <(apt-mark showmanual 2>/dev/null | sort) \
        <(dpkg --get-selections | grep deinstall | awk '{print $1}' | sort) \
        > "$dest" 2>/dev/null || dpkg --get-selections > "$dest"

    log "  → $dest"
}

# ---------------------------------------------------------------------------
# 6. venv pip freeze (JupyterHub venv + 추가 지정 venv)
# ---------------------------------------------------------------------------
backup_venv_freeze() {
    log "venv pip freeze 백업..."

    # freeze할 venv 목록 구성
    local venv_list=()
    [[ -n "$JUPYTERHUB_VENV" ]] && venv_list+=("$JUPYTERHUB_VENV")
    # EXTRA_VENVS를 단어 단위로 분리
    for v in $EXTRA_VENVS; do
        venv_list+=("$v")
    done

    if [[ ${#venv_list[@]} -eq 0 ]]; then
        warn "freeze 대상 venv 없음 — JUPYTERHUB_VENV 또는 EXTRA_VENVS를 설정하세요"
        return
    fi

    for venv_path in "${venv_list[@]}"; do
        local pip_bin="$venv_path/bin/pip"

        if [[ ! -x "$pip_bin" ]]; then
            warn "pip 없음: $pip_bin (스킵)"
            continue
        fi

        local env_name
        env_name=$(basename "$venv_path")
        local dest="$DEPLOY_DIR/venv_freeze/${env_name}.txt"

        if $DRY_RUN; then
            echo "[DRY-RUN] $pip_bin freeze → $dest"
            continue
        fi

        "$pip_bin" freeze 2>/dev/null > "$dest" \
            || { warn "  pip freeze 실패: $venv_path (스킵)"; continue; }

        local pkg_count
        pkg_count=$(wc -l < "$dest")
        log "  → $dest (${pkg_count}개 패키지)"
    done
}

# ---------------------------------------------------------------------------
# 7. 백업 메타데이터
# ---------------------------------------------------------------------------
write_meta() {
    local dest="$DEPLOY_DIR/backup_meta.txt"

    if $DRY_RUN; then
        echo "[DRY-RUN] 메타데이터 → $dest"
        return
    fi

    {
        echo "backup_date=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        echo "hostname=$(hostname)"
        echo "os=$(. /etc/os-release && echo "$PRETTY_NAME")"
        echo "python_version=$(python3 --version 2>&1)"
        echo "jupyterhub_venv=$JUPYTERHUB_VENV"
        echo "jupyterhub_venv_python=$("$JUPYTERHUB_VENV/bin/python" --version 2>/dev/null || echo 'N/A')"
        echo "jupyterhub_version=$("$JUPYTERHUB_VENV/bin/jupyterhub" --version 2>/dev/null || echo 'N/A')"
        echo "ollama_version=$(ollama --version 2>/dev/null || echo 'N/A')"
        echo "kernel=$(uname -r)"
        echo "git_commit=$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo 'N/A')"
    } > "$dest"

    log "  → $dest"
}

# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
main() {
    log "===== GCP VM 환경 백업 시작 ====="
    $DRY_RUN && log "[DRY-RUN 모드: 실제 파일 변경 없음]"

    init_dirs
    backup_jupyterhub_config
    backup_systemd_services
    backup_requirements
    backup_apt_packages
    backup_venv_freeze
    write_meta

    log "===== 백업 완료: $DEPLOY_DIR ====="
    log ""
    log "다음 단계: env 스냅샷을 backup_<날짜> 브랜치로 커밋·푸시"
    log "  bash \"$SCRIPT_DIR/commit_env_snapshot.sh\""
    log "  (단순 커밋만: git -C \"$SCRIPT_DIR\" add deploy/ && git -C \"$SCRIPT_DIR\" commit -m 'chore: env snapshot $(date +%Y-%m-%d)')"
}

main "$@"
