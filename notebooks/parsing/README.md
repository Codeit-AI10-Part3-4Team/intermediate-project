# notebooks/parsing/

## 역할
PDF/HWP 문서 파싱 검증 및 문서 구조 분석 노트북을 보관합니다.

## 담당
유빈님

## 현재 작업
- 데이터 확인
- PDF/HWP 파싱 검증
- 문서 구조 분석
- 청킹 후보 조사

## 산출물 연계
- 분석 결과는 `notebooks/eval/`의 골든 데이터셋 구축 기준에 참고 자료로 쓰입니다.
- 검증된 파싱 로직은 추후 `src/rag_core/parsing/`으로 이전되어 함수화됩니다.
- 청킹 후보 조사 결과는 `notebooks/retrieval/`(희원님)의 청킹 초안 구현에 입력값이 됩니다.

## 코딩 에이전트 참고
- 이 폴더는 파싱 단계만 다룹니다. 임베딩/Retrieval 로직을 여기에 작성하지 마세요 (`notebooks/retrieval/` 담당 영역).
- 원본 PDF/HWP 샘플 파일은 `data/`에 두고 `.gitignore` 처리합니다. 노트북에 파일을 직접 첨부하지 마세요.
