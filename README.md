# 📄 공공기관 RFP 문서 분석 RAG 챗봇

코드잇 AI 엔지니어 10기 파트3 4팀 중급 프로젝트 — 공공기관 제안요청서(RFP)를 RAG(Retrieval-Augmented Generation) 기반으로 분석하고 질의응답하는 서비스입니다.

> **기간**: 2026-06-17 ~ 07-08  
> **팀**: Codeit AI 10기 Part3 Team 4

---

## 팀 구성

| 이름 | 역할 | 담당 |
| --- | --- | --- |
| 재철 | PM (Project Manager) | 일정 관리, 골든 데이터셋 구축, 평가 설계 |
| 희원 | Retrieval Engineer | 청킹, 임베딩, Vector DB 구축 및 검색 파이프라인 |
| 지우 | Generation Engineer | LLM 실험, 프롬프트 엔지니어링, 후처리 |
| 유빈 | Data Engineer | 데이터 수집, EDA, 전처리, HWP/PDF 파싱 |
| 호정 | Backend/Infra | GCP VM, JupyterHub, API 서버, GitHub 관리 |
---

## 프로젝트 목표

공공기관 제안요청서(RFP)는 수십~수백 페이지에 달하는 문서로 구성되어 있어
사업 목적, 요구사항, 예산, 일정, 평가 기준 등을 파악하는 데 많은 시간이 소요됩니다.

본 프로젝트는 RAG(Retrieval-Augmented Generation) 기반 챗봇을 통해

- RFP 요약
- 문서 기반 질의응답
- 문서 비교
- 입찰 적합도 분석
- 근거 기반 답변 제공
- 리스크 분석
- 평가 기준 분석
- 유사 사업 추천
- 법령 근거 분석
- 연관 질문 추천
- 문체 변환

기능을 지원하는 것을 목표로 합니다.

---

## 프로젝트 파이프라인

```
RAG 파이프라인

[데이터 준비]
  공공기관 RFP 원본 문서 (PDF/HWP)
  → EDA 및 데이터 전처리 (유빈)
  → Metadata 추출 (유빈)
  → JSON 변환 (doc_id, sections, metadata)

        ↓

[Retrieval]
  Chunking (희원) — 섹션/표 단위 청킹
  → Embedding (희원)
  → Vector DB 저장 (희원) — ChromaDB

        ↓ 사용자 질문 입력

[검색]
  질문 임베딩 → ChromaDB 유사도 검색
  → Retrieved Context (청크 + 메타데이터)

        ↓

[Generation]
  Prompt Template (지우) + Retrieved Context
  → LLM (지우)
  → 사용자 답변
```

---

## 프로젝트 구조

```
intermediate-project/
├── data/                  # 데이터 (실제 파일은 .gitignore 처리)
│   └── chroma_db/         # Vector DB (공유 드라이브에서 다운로드)
├── docs/                  # 기획·의사결정 문서
├── eval/                  # 평가 자산
│   ├── golden_dataset/    # 골든 데이터셋 (123개 QA)
│   ├── metrics.py         # 평가 지표 계산 함수
│   └── eval_criteria.md   # 평가 기준 문서
├── notebooks/             # Jupyter Notebooks
│   ├── data/              # EDA, 전처리 실험
│   ├── retrieval/         # 청킹, 임베딩, 검색 실험
│   ├── llm/               # LLM, 프롬프트 실험
│   └── eval/              # 평가 실험
├── src/                   # 공유 Python 모듈
│   ├── rag_core/
│   │   ├── chunking/      # Chunker
│   │   ├── embedding/     # Embedder
│   │   ├── retrieval/     # ChromaRetriever
│   │   ├── schemas.py     # 데이터 스키마
│   │   └── interfaces.py  # 인터페이스 정의
│   └── api/               # FastAPI 서버
├── scripts/               # 실행 스크립트
├── tests/                 # 테스트 코드
└── .github/               # PR 템플릿, Issue 템플릿
```

---

## 환경 설정

### 사전 요구사항

- Python 3.12+
- GCP VM (JupyterHub) 접속 권한
- ChromaDB (공유 드라이브 및 VM)

### 설치

```bash
git clone https://github.com/Codeit-AI10-Part3-4Team/intermediate-project.git
cd intermediate-project

# 가상환경 생성
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

```

### Vector DB 설정

```bash
# 공유 드라이브에서 chroma_db 다운로드 후
mkdir -p data/chroma_db
# 다운로드한 chroma_db 폴더를 data/chroma_db/에 넣기
```

> ⚠️ ChromaDB는 Linux 환경에서 생성되었으므로 **WSL/Linux 또는 GCP 서버**에서 실행하세요.

---

## 평가 지표

| 단계 | 지표 |
| --- | --- |
| Retrieval | Retrieval Accuracy, Context Recall, Context Precision |
| Generation | Faithfulness, Answer Relevance, Response Time |
| 기능 | 적합도 분석, 문서 비교, 법령 분석 |

---

## 브랜치 전략

| 브랜치 | 용도 |
| --- | --- |
| `main` | 항상 동작 가능한 상태 유지. PR + 1인 리뷰 필수 |
| `feature/<작업내용>` | 기능 개발 및 실험 버전 |

---

## 데이터셋

- 공공기관 RFP 문서 100개 (HWP 96건, PDF 4건)
- 골든 데이터셋 v2: 123개 QA (Retrieval 101개 + Generation 22개)
