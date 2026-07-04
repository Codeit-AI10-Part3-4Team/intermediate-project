# ㅇㅇㅍ 디자인 시스템 (`frontend/design/`)

RFP RAG 서비스 프론트엔드의 브랜드 디자인 자산입니다 (스펙 v2, 2026-07-04).
컨셉: 그린·화이트의 단정한 UI + 선명한 텍스트. 라이트 단일 테마.

## 구성

- `tokens.css` — 디자인 토큰 단일 원천(CSS 커스텀 프로퍼티)
- `logo/oop-logo.svg` — ㅇㅇㅍ 워드마크(순수 벡터, 폰트 비의존)
- `fonts/` — 나눔고딕 woff2 (400/700/800, 한글 서브셋) + `LICENSE-OFL.txt`
  - SIL Open Font License 1.1 — 상업 사용·재배포 허용, 라이선스 파일 동봉 필수
- `previews/` — 컴포넌트·화면 목업 HTML (Claude Design 카드용, 브라우저로 직접 열람 가능)

## Streamlit 매핑 (적용 완료 — `frontend/.streamlit/config.toml`)

```toml
# frontend/.streamlit/config.toml
[theme]
base = "light"
primaryColor = "#8C9963"
backgroundColor = "#F2F2ED"
secondaryBackgroundColor = "#FFFFFF"
textColor = "#2C3323"
```

폰트는 `enableStaticServing` + `[[theme.fontFaces]]`로 셀프 호스팅(CDN 미의존).
세부 스타일(말풍선 우측 정렬 등)은 data-testid 기반 CSS 최소 주입 —
내부 클래스(st-emotion-cache-*) 의존 금지(버전 업 시 파손).
컴포넌트별 CSS 구현은 `frontend/styles.py`, 구현 주의사항(동기 pending 흐름,
fragment/iframe 금지 등)은 `frontend/README.md` 참고.

## 색 사용 규칙

- `#8C9963`(Primary)는 버튼·액센트 전용 — 본문 텍스트 금지(대비 3.1:1, AA 미달)
- 본문은 `#2C3323`(Ink, 11.1:1), 캡션은 `#6A7060`(4.6:1)
- 강조 텍스트가 필요하면 `#57633F`(Green 700)
