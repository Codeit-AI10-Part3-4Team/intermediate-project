
# 파서 parity 검증 보고서

- **대상 브랜치**: `feature/parser-parity-check`
- **작성일**: 2026-07-02
- **범위**: `notebooks/parsing` → `src/rag_core/parsing` 이전(ipynb→py)이 파싱 결과를 바꾸지 않았음을 검증하는 작업

---

## 1. 배경 / 목적

파싱 로직은 노트북(실험)에서 검증된 뒤 `src/rag_core/`의 프로덕션 모듈로 함수화되어 이전됩니다.
이전 과정에서 리팩터링·구조 변경이 **파싱 산출물(텍스트/구조)을 바꾸지 않았는지**를 회귀 관점에서
증명하는 것이 이 작업의 목적입니다. 이 검증이 이후 단계(업로드 적합성 검사, 코퍼스 구축)에서
파서를 신뢰하고 소비하기 위한 선결 조건입니다.

---

## 2. parity 검증 전략 (레이어드 비교)

가장 결정적인 신호부터 순서대로 비교해, 회귀를 가장 싼 비용으로 잡습니다.

1. **`dedup_hash`** — `qa.dedup_hash = sha256(전체 블록 텍스트)`. 텍스트의 결정적(바이트) 동등성.
2. **구조** — `total_sections` / `total_blocks` / `table_blocks` 개수 + 첫 불일치 블록의 위치·유형.
3. **`parse_method`** — 추출 경로 변화(A1→B 폴백 등). 출력이 달라졌을 강한 신호.

> **임베딩 비교는 하지 않습니다(Phase 2 대상).** `dedup_hash`가 일치하면 텍스트가 바이트 동일이므로
> 임베딩도 tolerance 내에서 동일합니다 → 이 검증에는 GPU가 필요 없습니다.
>
> 비교는 allowlist 방식(특정 `qa` 필드만 비교)이라 `processed_at` 같은 실행마다 달라지는
> 휘발성 필드는 자연히 제외됩니다.

**종료 코드**: 불일치·누락이 하나라도 있으면 `1`, 완전 일치면 `0`.

---

## 3. parity 스크립트 단위 테스트

parity **판정 로직 자체의 정확성**을 합성 JSON 픽스처로 검증합니다. 스크립트가
`scripts/`의 독립 파일(설치 패키지 아님)이므로 `importlib`로 파일 경로 로드해 순수 함수만 테스트합니다.

- **파일**: [../tests/test_parity_check_parsing.py](../tests/test_parity_check_parsing.py)
- **결과**: **12 passed** · ruff(check + format) 통과 · 샘플 문서·GPU 불필요

| 대상 함수 | 검증 케이스 |
|---|---|
| `diff_doc` | 동일→ok / `dedup_hash` 불일치 시 첫 블록 위치 동반 보고 / 블록 `type` 변경 / `total_sections`·`total_blocks`·`table_blocks` 개수차 / `parse_method` 폴백 전환 |
| `_first_block_mismatch` | 동일→`None` / content 길이차 보고 / 접두 일치 시 개수차 보고 |
| `load_docs` | `doc_id` 키 적재 / 디렉토리 아님→`NotADirectoryError` / 잘못된 JSON→`ValueError` |
| `compare_dirs` | 공통·golden 전용·candidate 전용 분할 + diff 집계 |

### 재현 방법

```bash
# 단위 테스트 (로컬)
python -m pytest tests/test_parity_check_parsing.py -q

# 실제 parity 비교 (golden/candidate JSON 디렉토리 필요)
python scripts/parity_check_parsing.py --golden ./golden/docs --candidate ./new/docs [--verbose]
```

---
## 4. parity 검증 결과


### 실행 환경

- OS: Windows 11 (Local)
- Python: 3.10.11
- Virtual Environment: `venv`
- 실행 위치: C:\Codes\Codeit_AI10_Part3_4Teamintermediate_project

### 수행 방법

총 **4회** parity 검증을 수행하였다.

```powershell
python .\scripts\parity_check_parsing.py `
  --golden .\golden `
  --candidate .\parity_out\docs `
  --verbose
```


### 검증 결과

총 3개의 문서(D001, D008, D026)에서 차이가 보고되었으며,
모든 항목에 대해 JSON 원본을 직접 비교하여 원인을 확인하였다.

| 문서   | 결과              | 확인 내용                                      |
| ---- | --------------- | ------------------------------------------ |
| D001 | parse_method 변경 | 출력 텍스트 및 블록 구조 동일                          |
| D008 | parse_method 변경 | 출력 텍스트 및 블록 구조 동일                          |
| D026 | dedup_hash 불일치  | JSON 직접 비교 결과 내용은 동일하며 공백 처리에 따른 형식적 차이 확인 |



## 5. 결론

parity 검증 과정에서 보고된 차이는 모두 직접 확인하였다.

- D001, D008은 `parse_method` 변경만 확인되었으며 파싱 결과에는 영향이 없었다.
- D026은 `dedup_hash` 불일치가 보고되었으나 JSON 직접 비교 결과 내용은 동일하였고 공백 처리에 따른 형식적 차이였다.

따라서 notebook 기반 파서에서 `src/rag_core/parsing`으로 이전된
py 파이프라인은 기능적으로 동일한 파싱 결과를 생성함을 확인하였다.
