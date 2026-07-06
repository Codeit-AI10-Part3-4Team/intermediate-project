#!/usr/bin/env bash
# vector_db 디렉토리에 서비스 그룹(vectordb) 쓰기 권한을 (재)적용한다 — 멱등.
#
# 왜 필요한가:
#   /data/vector_db 부모에는 default ACL(group:vectordb:rwx)이 걸려 있지만, 새 DB를
#   cp/tar로 복사해 넣으면 파일은 644·디렉토리는 755 모드로 만들어지고, POSIX ACL은
#   그 "생성 모드의 그룹 비트"로 mask를 다시 계산한다. 그 결과 상속된 vectordb:rwx가
#   mask(r--/r-x)에 눌려 실효 read-only가 되고, chroma sqlite가 기동 시
#   "attempt to write a readonly database"로 즉사한다(2026-07-06 v9 사례).
#   → named 엔트리를 재적용하면 setfacl이 mask를 rwx로 다시 올려 실효 권한이 살아난다.
#
# 사용법 (새 vector_db 버전을 배치한 직후, sudo 권한 계정으로):
#   scripts/fix_vectordb_acl.sh /data/vector_db/vector_db_v9
#   VECTORDB_GROUP=other scripts/fix_vectordb_acl.sh <경로>   # 그룹명이 다르면
#
# 안전: 읽기 권한은 건드리지 않고 그룹 쓰기만 (재)부여한다. chown/소유권 변경 없음.
set -euo pipefail

GROUP="${VECTORDB_GROUP:-vectordb}"
TARGET="${1:-}"

if [[ -z "$TARGET" ]]; then
    echo "사용법: $0 <vector_db 경로>   (예: /data/vector_db/vector_db_v9)" >&2
    exit 2
fi
if [[ ! -d "$TARGET" ]]; then
    echo "[acl] 중단: 디렉토리가 아닙니다 — $TARGET" >&2
    exit 1
fi
if ! getent group "$GROUP" >/dev/null; then
    echo "[acl] 중단: '$GROUP' 그룹이 없습니다 (VECTORDB_GROUP로 재지정 가능)." >&2
    exit 1
fi

echo "[acl] $TARGET → g:$GROUP:rwX (재)적용 + default ACL 보강"
# 접근 ACL: rwX(디렉토리에만 x). setfacl이 mask를 그룹 엔트리 합집합으로 재계산한다.
sudo setfacl -R -m "g:$GROUP:rwX" "$TARGET"
# default ACL: 이 경로 하위에 앞으로 생길 것들도 같은 규칙을 물려받게.
sudo setfacl -R -d -m "g:$GROUP:rwX" "$TARGET"

# 검증: sqlite 파일들의 실효 권한에 w가 살아있는지 (#effective 에 r-- 이 남으면 실패).
bad=0
while IFS= read -r -d '' db; do
    if getfacl -p "$db" 2>/dev/null | grep -q "group:$GROUP:.*#effective:r[-x]*$"; then
        echo "[acl] ⚠️ 여전히 read-only 실효: $db" >&2
        bad=1
    fi
done < <(find "$TARGET" -name '*.sqlite3' -print0)

if [[ "$bad" == "1" ]]; then
    echo "[acl] ❌ 일부 파일의 실효 권한이 아직 read-only입니다 — getfacl로 mask를 확인하세요." >&2
    exit 1
fi

echo "[acl] ✅ 완료 — rfp-api 재기동으로 반영: sudo systemctl restart rfp-api"
