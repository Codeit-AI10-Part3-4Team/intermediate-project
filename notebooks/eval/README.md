# notebooks/eval/

## 역할
평가 계획 수립 및 골든 데이터셋 구축 과정을 기록하는 노트북을 보관합니다.

## 담당
PM

## 현재 작업
- 평가 계획 수립
- 골든 데이터셋 50개 구축 시작
- 실험 설계

## 산출물 연계
- 입력: `notebooks/parsing/`(유빈님), `notebooks/retrieval/`(희원님), `notebooks/llm/`(지우님) 각 단계의 중간 산출물
- 출력: 골든 데이터셋 초안 → 검증 완료 후 `eval/golden_dataset/`로 이전(버전 관리 대상)
- 출력: 평가 기준 문서 → `eval/eval_criteria.md`로 정리

## 코딩 에이전트 참고
- 골든 데이터셋이 최종 확정되면 이 노트북에서 데이터를 생성만 하고, 실제 데이터 파일은 `eval/golden_dataset/`에 저장합니다. 노트북과 데이터 파일을 혼재시키지 마세요.
- 평가 스크립트(`eval/metrics.py`)와 평가 계획 노트북은 역할이 다릅니다. 재사용 가능한 평가 함수는 노트북이 아닌 `eval/metrics.py`에 작성하세요.
