# ㅇㅇㅍ 디자인 시스템 — 사용 규약

정부 RFP 분석 RAG 서비스의 브랜드 디자인 시스템. **라이트 단일 테마, 한국어 UI.**
JS 컴포넌트 번들은 없습니다 — 일반 HTML/React 컴포넌트를 아래 토큰 어휘로 직접 스타일링해서 빌드하세요.

## 설정 (모든 화면 공통)

- 루트에 반드시: `background: var(--oop-bg); color: var(--oop-ink); font-family: var(--oop-font); font-size: var(--oop-fs-body); line-height: 1.7;`
- 폰트 Nanum Gothic은 `styles.css`의 @font-face로 로드됨(weight **400/700/800만** 존재 — 다른 굵기는 합성 렌더로 품질 저하).
- `html { color-scheme: light; }` — 다크 테마 없음.

## 토큰 어휘 (`tokens/tokens.css` — 스타일 작성 전 반드시 읽을 것)

- 색: `--oop-bg`(페이지 배경) · `--oop-surface`(카드·입력창 흰색) · `--oop-primary`/`--oop-primary-hover`/`--oop-primary-active`(버튼·액센트) · `--oop-green-700`(강조 텍스트) · `--oop-green-100`(연한 채움) · `--oop-user-bubble`(사용자 말풍선) · `--oop-ink`(본문) · `--oop-ink-muted`(캡션) · `--oop-border` · `--oop-success`/`--oop-success-bg` · `--oop-danger`/`--oop-danger-bg`
- 타이포: `--oop-font` · `--oop-fs-display`(26px, weight 800) · `--oop-fs-h2`(20px, 700) · `--oop-fs-body`(16px, 400) · `--oop-fs-caption`(13px)
- 형태: `--oop-radius-lg`(18px, 채팅 입력창) · `--oop-radius-md`(12px, 버튼·카드) · `--oop-radius-pill` · `--oop-shadow-sm` · `--oop-shadow-md`

## 색 사용 규칙 (접근성 — 위반 금지)

- `--oop-primary`(#8C9963)는 **버튼 배경·액센트 전용**. 텍스트 색으로 쓰지 말 것(배경 대비 3.1:1, AA 미달).
- 본문 텍스트 `--oop-ink`(대비 11.1:1) · 캡션 `--oop-ink-muted`(4.6:1) · 강조 텍스트는 `--oop-green-700`.
- primary 버튼 위 텍스트는 `#fff`. 비활성 primary 배경은 `#C7CCB6`.
- 포커스 링: `outline: 2px solid var(--oop-primary); outline-offset: 2px;`

## 진실의 원천

- `tokens/tokens.css` — 토큰 전체 정의
- `guidelines/brand.md` — 로고 SVG 원본(인라인 사용)과 브랜드 규칙
- `components/**/*.html` — 검증된 목업: 버튼(`components/buttons`), 채팅 입력창·말풍선(`components/chat`), 근거 청크 카드(`components/sources`), 업로드 판정 배지(`components/upload`), 홈·채팅 화면(`screens/*`)

## 관용 스니펫 (검증된 프리뷰에서 발췌)

```html
<button style="display:inline-flex;align-items:center;gap:8px;
  background:var(--oop-primary);color:#fff;border:0;cursor:pointer;
  border-radius:var(--oop-radius-md);padding:12px 20px;
  font:700 15px/1 var(--oop-font);">질의하기</button>

<div style="background:var(--oop-surface);border:1px solid var(--oop-border);
  border-radius:var(--oop-radius-md);box-shadow:var(--oop-shadow-sm);padding:16px;">카드 내용</div>

<div style="background:var(--oop-user-bubble);border-radius:16px 16px 4px 16px;
  padding:12px 18px;max-width:70%;margin-left:auto;width:fit-content;">사용자 말풍선(오른쪽 정렬)</div>
```
