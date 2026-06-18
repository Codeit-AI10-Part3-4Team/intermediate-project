# notebooks/

## 역할
조사·실험 단계의 Jupyter 노트북을 보관하는 디렉토리입니다.
`src/`의 프로덕션 코드와 분리되어 있으며, 여기 있는 코드는 **실행 가능한 실험 기록**이지 배포 대상이 아닙니다.

## 하위 폴더
- `parsing/` — PDF/HWP 파싱 검증, 문서 구조 분석 (담당: 유빈님)
- `retrieval/` — 임베딩 모델·Retrieval 방식 후보 실험 (담당: 희원님)
- `llm/` — LLM 후보 조사, 프롬프트 실험 (담당: 지우님)
- `eval/` — 평가 계획, 골든 데이터셋 구축 과정 (담당: PM)

## 규칙
- 노트북 파일(`*.ipynb`)은 commit 전 출력(output)이 자동으로 제거됩니다 (`nbstripout` 적용, `.gitattributes` 참고).
  - 이미지/표 결과를 보존하고 싶다면 `notebooks/<폴더>/figures/`에 별도 이미지로 저장하세요.
- 노트북에서 검증이 끝난 로직은 **반드시 `src/rag_core/` 하위의 대응 모듈로 옮겨서 함수화**합니다. 노트북 자체를 import해서 쓰지 않습니다.
- 셀 실행 순서가 섞이지 않도록, 커밋 전 `Restart Kernel and Run All`로 한 번 검증 후 커밋합니다.

## 코딩 에이전트 참고
- 이 디렉토리의 코드를 프로덕션 의존성으로 import하지 마세요. `src/rag_core/`에 동등한 모듈이 있는지 먼저 확인하세요.
- 새 실험 노트북을 만들 때는 파일명에 날짜 또는 버전을 포함합니다. 예: `chunking_experiment_v2.ipynb`.
