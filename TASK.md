# MathHub 작업 이력

## Phase 0: 기반 구축

### 1. Monorepo 초기 구조 생성 (pnpm) — `be4fa7a`
- [x] 루트 설정 (`package.json`, `pnpm-workspace.yaml`, `.npmrc`, `.gitignore`)
- [x] Next.js 앱 스캐폴딩 (`apps/web`)
- [x] FastAPI 스켈레톤 (`apps/api`)
- [x] 공유 타입 패키지 (`packages/shared`)
- [x] Docker Compose (Postgres + Redis)

### 2. UI/UX 디자인 시스템 + 5 핵심 화면 — `970f6b5`
- [x] MUI 다크 테마 (4색 팔레트: `#262A2D`, `#919497`, `#E7E3E3`, `#FFFFFF`)
- [x] 레이아웃 쉘 (Sidebar, TopBar, AppShell)
- [x] 대시보드 `/` (통계 카드 + 최근 작업 + 빠른 업로드)
- [x] PDF 업로드 `/upload`
- [x] 작업 목록 `/jobs`
- [x] 문제 라이브러리 `/problems`
- [x] 검수 큐 `/review`
- [x] Mock 데이터 (한국어 수학 문제)

### 3. 사이드바 오버랩 수정 — `868de4a`
- [x] Sidebar: `position: fixed` → `sticky`, `flexShrink: 0`
- [x] AppShell: `flex` 레이아웃 복원, `marginLeft` 제거

### 4. 2027 수능 수학 DB 스키마 설계 — `b6e9e0b`
- [x] OCR(Mathpix) 파이프라인용 DB 스키마 추가 (`ocr_documents`, `ocr_jobs`, `ocr_pages`)
- [x] 문제은행 스키마 추가 (`problems`, `problem_choices`, `problem_unit_map`, `problem_assets`, `problem_revisions`)
- [x] 2027 수능 수학 기준값 반영 (수학Ⅰ/수학Ⅱ + 확률과 통계/미적분/기하, 2·3·4점, 30문항/100점/100분)
- [x] 단원 트리 시드 추가 (대단원/중단원 2단계)
- [x] DB 설계 문서 추가 (`apps/api/db/README.md`)
