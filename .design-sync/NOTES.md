# design-sync NOTES

- 이 저장소는 JS 컴포넌트 라이브러리가 아님(파이썬 프로젝트 + 손으로 작성한 브랜드 자산
  `frontend/design/`). 컨버터(`package-build.mjs`) 대신 **오프스크립트 빌더**
  `.design-sync/build_bundle.py <출력경로>` 로 번들을 생성 — JS 번들(`_ds_bundle.js`)·
  `_vendor/`는 원래 존재하지 않으므로 업로드하지 않음(토큰+폰트+브랜드 전용 DS).
- `_ds_sync.json`(싱크 앵커)은 **의도적으로 생략** — 오프스크립트 경로라 storybook/package
  해시 레시피를 재현할 수 없음. 다음 동기화는 앵커 없이 전체 재검증(파일 18개 규모라 부담 없음).
- 검증: 정적 검사(빌더에 내장 — @dsCard 마커, url() 경로 해석, `var(--oop-*)` 정의 대조,
  woff2 매직 바이트, SVG XML 파싱, conventions 어휘 대조). 이 WSL 환경에는 헤드리스 브라우저가
  없어 렌더 스크린샷 검증은 불가 — 시각 검증은 원본 프리뷰에 대해 2026-07-04 리뷰 Artifact로 수행됨.
- 카드 배치: `previews/<f>.html` → `components/<group>/<slug>/<slug>.html`, 폰트 상대경로
  `../fonts/` → `../../../fonts/` 재작성 (빌더의 CARD_MAP이 단일 원천 — 프리뷰 추가 시 여기 갱신).
- 번들 출력은 저장소 밖(세션 스크래치패드)에 생성 — 저장소를 오염시키지 않으며 매 동기화마다 재빌드.
- 인증: 일반 `/login` 토큰으로는 design scope 부여 불가(400). **`/design-login`** 이 정답
  (2026-07-04 확인).
