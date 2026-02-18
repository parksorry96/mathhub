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

### 5. 문제 출처 분류 확장(기출/연계교재/기타) — `1d54ca2`
- [x] 출처 상위분류 추가 (`problem_source_category`: `past_exam`, `linked_textbook`, `other`)
- [x] 출처 세부분류 확장 (`problem_source_type`: 수능/평가원모평/교육청학평/EBS연계/사설모의/문제집 등)
- [x] 출처 상세 메타데이터 컬럼 추가 (`academic_year`, `exam_year`, `exam_session`, `series_name`, `source_url` 등)
- [x] 문항 번호 저장 컬럼 추가 (`problems.source_problem_no`, `problems.source_problem_label`)
- [x] 출처-문항번호 중복 방지 유니크 인덱스 및 분류 무결성 체크 제약 추가
- [x] 출처 예시 시드 추가 (`seed_csat_2027_math.sql`)
- [x] 일반 수학 문항검색 서비스/공식 사이트 리서치 근거를 README에 반영

### 6. Alembic 마이그레이션 체계 도입 — `7f9ae1c`
- [x] API 의존성에 DB 마이그레이션 패키지 추가 (`alembic`, `sqlalchemy`, `psycopg[binary]`)
- [x] Alembic 초기 설정 파일 추가 (`apps/api/alembic.ini`, `apps/api/migrations/*`)
- [x] baseline 리비전 추가 (`d23823e2de6d`) 및 고정 스키마 스냅샷 도입
- [x] baseline `upgrade/downgrade` 경로 구현 (테이블/타입 생성 및 롤백)
- [x] 루트 실행 스크립트 추가 (`db:current`, `db:upgrade`, `db:downgrade`, `db:seed:csat2027`)
- [x] DB README에 마이그레이션 실행 방법 문서화
- [x] 라이브 DB(`mathhub`)를 Alembic `head`로 정렬하여 버전 테이블 반영

### 7. OCR Job API 1차 구현 — `f4722e1`
- [x] DB 연결 유틸 추가 (`app/config.py`, `app/db.py`)
- [x] OCR Job 요청/응답 스키마 추가 (`app/schemas/ocr_jobs.py`)
- [x] OCR Job 라우터 추가 (`POST /ocr/jobs`, `GET /ocr/jobs/{job_id}`)
- [x] FastAPI 메인 앱에 OCR Job 라우터 연결
- [x] 유효성/예외 처리 반영 (SHA-256 패턴, UUID path validation, unique 충돌 409, 미존재 404)
- [x] 별도 검증 DB에서 통합 테스트 수행 (생성/조회/404/422/409 시나리오 통과)

### 8. OCR AI 분류(API 키 기반) 추가 — `11e354c`
- [x] OpenClaw 워크플로우 대신 일반 AI API 키 기반 분류 전략으로 전환
- [x] AI 분류 서비스 추가 (`apps/api/app/services/ai_classifier.py`)
- [x] OCR Job AI 분류 API 추가 (`POST /ocr/jobs/{job_id}/ai-classify`)
- [x] 분류 결과를 `ocr_pages.raw_payload` 및 `ocr_jobs.raw_response`에 JSONB로 저장
- [x] `UUID/Datetime/Decimal` JSON 직렬화 보강으로 저장 오류 해결
- [x] API 키 미설정/호출 실패 시 휴리스틱 분류 fallback 반영
- [x] 의존성 추가 (`httpx`) 및 정적 점검 통과
- [x] 통합 검증 수행 (job 생성 → page 적재 → ai-classify → DB 저장 확인)

### 9. OCR 분류결과 문제은행 적재 API 추가 — `4cc06f9`
- [x] `POST /ocr/jobs/{job_id}/materialize-problems` 엔드포인트 추가
- [x] AI 분류 결과(`ocr_pages.raw_payload.ai_classification.candidates`)를 `problems`로 upsert
- [x] `external_problem_key` 고정 키 전략으로 재실행 시 idempotent 업데이트 보장
- [x] 과목코드 미매핑/신뢰도 미달/본문 누락 후보는 `skipped`로 분리 처리
- [x] 단원코드가 유효한 경우 `problem_unit_map` primary 매핑 반영
- [x] `needs_review` 메타데이터를 기본 부여해 후속 검수 흐름 유지
- [x] 통합 검증 수행 (1차 insert, 2차 update, DB 반영 확인)

### 10. Mathpix 제출/동기화 OCR 자동화 API 추가 — `7e496bb`
- [x] `POST /ocr/jobs/{job_id}/mathpix/submit` 엔드포인트 추가
- [x] `POST /ocr/jobs/{job_id}/mathpix/sync` 엔드포인트 추가
- [x] Mathpix 클라이언트 서비스 분리 (`submit`, `status`, `job_id 추출`, `상태 매핑`, `페이지 추출`)
- [x] sync 시 `ocr_pages` upsert 및 `ocr_jobs` 상태/진행률/에러/원본 응답 갱신
- [x] `submit -> sync -> ai-classify -> materialize` 전체 체인 검증 통과
- [x] `source_problem_no` 충돌 리스크 반영(`NULL` 기본 + `source_problem_label` 사용)

### 11. 프론트 실API 연동 및 mock 제거 — `b1ea290`
- [x] mock 데이터 파일 제거 (`apps/web/src/mocks/data.ts`)
- [x] 웹 API 클라이언트 추가 (`apps/web/src/lib/api.ts`)
- [x] 대시보드 페이지를 실제 API 데이터 기반으로 전환 (`/`, `GET /ocr/jobs`, `GET /problems`)
- [x] 작업 목록 페이지를 실연동으로 전환하고 액션 버튼 연결 (`submit/sync/classify/materialize`)
- [x] 업로드 페이지를 `POST /ocr/jobs` 기반 등록 흐름으로 전환 (SHA-256 계산 포함)
- [x] 문제 라이브러리 페이지를 `GET /problems` 기반으로 전환
- [x] 검수 페이지를 `GET /problems` + `PATCH /problems/{id}/review` 기반으로 전환
- [x] 백엔드에 프론트용 목록/검수 API 추가 (`GET /ocr/jobs`, `GET /problems`, `PATCH /problems/{id}/review`)
- [x] 정적 검증/빌드/통합 검증 완료 (web lint/build, api ruff/compile, end-to-end API 시나리오)
