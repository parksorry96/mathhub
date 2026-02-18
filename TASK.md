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

### 12. S3 Presigned 업로드 흐름 추가 — `aff74fa`
- [x] S3 설정 env getter 추가 (`S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` 등)
- [x] S3 서비스 추가 (`apps/api/app/services/s3_storage.py`: key 생성, storage_key 파싱, presigned PUT/GET)
- [x] S3 presign API 추가 (`POST /storage/s3/presign-upload`)
- [x] `mathpix/submit`에서 `storage_key=s3://bucket/key`일 때 presigned GET URL 자동 생성
- [x] 웹 업로드 페이지를 `presign -> S3 PUT -> POST /ocr/jobs` 흐름으로 전환
- [x] 웹 API 클라이언트에 S3 presign/PUT 유틸 추가 (`apps/web/src/lib/api.ts`)
- [x] 정적 검증/빌드/통합 검증 완료 (api ruff/compile, web lint/build, temp DB 시나리오)

### 13. API 환경변수 샘플 추가 — `3883ae4`
- [x] API 실행용 `.env.example` 추가 (`apps/api/.env.example`)
- [x] Mathpix/AI/S3 필수 및 선택 환경변수 템플릿 정리

### 14. API `.env` 자동 로드 및 빈값 정규화 — `96d1f70`
- [x] API 시작 시 `apps/api/.env` 자동 로드 추가 (`python-dotenv`)
- [x] 환경변수 빈 문자열을 `None`으로 정규화하도록 `config` getter 공통화
- [x] `S3_ENDPOINT_URL=` 빈값일 때 boto3 `Invalid endpoint` 오류 해결
- [x] 의존성 반영 (`apps/api/pyproject.toml`, `apps/api/requirements.txt`)

### 15. S3 Presigned URL CORS 호환 엔드포인트 보정 — `f9952cb`
- [x] presigned URL 기본 호스트를 글로벌(`s3.amazonaws.com`)에서 리전 엔드포인트(`s3.<region>.amazonaws.com`)로 보정
- [x] `S3_ENDPOINT_URL`이 명시된 경우 사용자 지정 엔드포인트 우선 사용 유지
- [x] 로컬에서 `/storage/s3/presign-upload` URL 호스트가 리전으로 생성되는지 검증
- [x] 브라우저와 동일한 `OPTIONS` preflight로 CORS 헤더 응답(200) 검증

### 16. Legacy storage_key 오류 가드 및 UX 보완 — `f77c828`
- [x] Mathpix submit에서 `upload://` legacy 키 감지 시 원인/조치가 포함된 명확한 오류 메시지 반환
- [x] OCR Job 생성 시 `storage_key`를 `s3://` 또는 `http(s)://`만 허용하도록 검증 추가
- [x] 작업 목록에서 legacy `storage_key` 작업의 Mathpix 제출 버튼 비활성화 및 툴팁 안내 추가
- [x] API/프론트 정적 검증 및 실제 엔드포인트 동작 검증 완료

### 17. S3 중복업로드/작업삭제 흐름 보강 — `34b718c`
- [x] `sha256` 중복 업로드 시 `ocr_documents`가 최신 `storage_key`(S3)로 갱신되도록 upsert 로직 개선
- [x] Mathpix `/pdf` 제출 payload에서 지원되지 않는 `conversion_formats` 제거 및 에러 메시지 보강
- [x] OCR 작업 삭제 API 추가 (`DELETE /ocr/jobs/{job_id}`) 및 고아 문서 정리/선택적 S3 삭제 시도
- [x] 작업 목록 페이지에 삭제 버튼(확인창 포함) 추가 및 실 API 연동
- [x] 회귀 검증: 신규 submit 성공, legacy 문서 S3 재바인딩, 삭제 API 동작 확인

### 18. 작업목록 페이지 수(0/0) 표시 보정 — `79a37be`
- [x] `ocr_pages`가 비어 있어도 `raw_response.mathpix_status.num_pages(_completed)`를 fallback으로 사용하도록 목록 집계 SQL 보완
- [x] API 응답 검증: 완료된 Mathpix 작업에서 `total_pages/processed_pages`가 실제 페이지 수(예: 20/20)로 노출됨 확인

### 19. AI 분류 400 원인 해소 및 OCR 확인 기능 추가 — `0c0fdf8`
- [x] Mathpix sync 시 기본 상태 응답에서 페이지 추출 실패하면 `/pdf/{id}.lines.json` 추가 조회로 `ocr_pages` 채움
- [x] `GET /ocr/jobs/{job_id}/pages` API 추가로 페이지별 OCR 텍스트 확인 경로 제공
- [x] 작업 목록 UI에 OCR 미리보기 버튼/다이얼로그 추가 (`/pages` API 연동)
- [x] AI 분류 에러 메시지 개선 (페이지 없음 시 sync/pages 확인 가이드 제공)
- [x] 실검증: 대상 job sync 후 `pages_upserted=20`, `/pages` total=20, `ai-classify` 400 재현 해소 확인

### 20. AI 분류 단계진행 UX + 재검수 큐 보강 — `9b818b7`
- [x] `POST /ocr/jobs/{job_id}/ai-classify/step` 추가로 문항 단위(1건) AI 분류 진행
- [x] `raw_response.ai_classification` 진행요약(`processed/total/done/provider/model`) 저장 및 `GET /ocr/jobs` 노출 필드 확장
- [x] 작업목록에서 AI 진행상황(`AI processed/total`, provider, 승인 수) 즉시 확인 UI 추가
- [x] 작업목록 AI 분류 동작을 step-loop 방식으로 전환해 진행중 상태를 실시간 안내
- [x] OCR 미리보기에서 LaTeX 텍스트를 `better-react-mathjax`로 렌더링하도록 개선
- [x] `GET /problems`에 `ai_reviewed` 필터 및 AI 메타(provider/model) 노출 추가
- [x] 검수 큐에 `AI 분류 문항만` 토글/배지/메타표시 추가로 사람 재검수 흐름 보강
- [x] 검증 완료 (`ruff`, `compileall`, `web lint/build`, 실제 step/API 호출로 진행률 증가 확인)

### 21. 작업목록 원클릭 자동실행 파이프라인 추가 — `e362232`
- [x] 작업목록에 자동실행 버튼 추가 (`제출 → 동기화 폴링 → AI step 분류 → 문제 적재`)
- [x] 자동실행 중 단계별 진행 문구를 표시하도록 UX 보강
- [x] `sync/materialize` 응답 타입을 API 클라이언트에 명시해 타입 안정성 강화
- [x] legacy `upload://` 작업은 자동실행 시작 불가하도록 비활성/툴팁 처리
- [x] 검증 완료 (`pnpm --filter @mathhub/web lint`, `pnpm --filter @mathhub/web build`)

### 22. 검수 화면 수식 렌더링 적용 — `47b4cce`
- [x] 검수 본문(`review`)에 `better-react-mathjax` 적용
- [x] OCR/AI에서 넘어온 LaTeX가 텍스트가 아니라 수식 형태로 보이도록 UX 개선
- [x] 기존 검수 플로우(승인/반려/이전/다음) 동작 유지
- [x] 검증 완료 (`pnpm --filter @mathhub/web lint`, `pnpm --filter @mathhub/web build`)

### 23. 문항 단위 미리보기 + 시각 자산 적재 강화 — `e1789d9`
- [x] 하이브리드 문항 분리 규칙 확장(`숫자.`, `[숫자]`, `문항 n`, `n번`) 및 fallback 전략 적용
- [x] `GET /ocr/jobs/{job_id}/questions` API 추가로 문항 단위 미리보기 데이터 제공
- [x] 작업 목록 미리보기를 페이지 단위에서 문항 단위(list-detail) UI로 개편하고 가독성 개선
- [x] 그림/그래프/표 힌트 추출을 `materialize-problems`에 연결하여 `problem_assets` upsert 저장
- [x] 검증 완료 (`ruff check`, `python -m compileall`, `pnpm --filter @mathhub/web lint`, `pnpm --filter @mathhub/web build`)

### 24. 구버전 API 404 대응 미리보기 fallback — `2a1ab16`
- [x] `/ocr/jobs/{job_id}/questions` 404 시 `/ocr/jobs/{job_id}/pages`로 자동 fallback 처리
- [x] fallback 경로에서 클라이언트 문항 분할(`숫자.`, `[숫자]`, `문항 n`, `n번`) 적용
- [x] fallback 경로에서도 시각요소(그림/그래프/표) 힌트 태그 유지
- [x] 검증 완료 (`pnpm --filter @mathhub/web lint`, `pnpm --filter @mathhub/web build`)

### 25. AI 분류 속도 개선(배치 step 처리) — `c81b2bd`
- [x] `OCRJobAIClassifyRequest`에 `max_candidates_per_call`(기본 5, 최대 50) 추가
- [x] `POST /ocr/jobs/{job_id}/ai-classify/step`가 호출당 1문항이 아니라 다문항 배치 처리하도록 개선
- [x] 프론트 classify loop에서 `max_candidates_per_call: 8`로 요청해 왕복 횟수 감소
- [x] 검증 완료 (`ruff check`, `python -m compileall`, `pnpm --filter @mathhub/web lint`, `pnpm --filter @mathhub/web build`)

### 26. 문항 시각 자산 추출/저장/미리보기 연동 — `23e2815`
- [x] `ProblemAssetExtractor` 서비스 추가(PDF clip 렌더링 → PNG bytes → S3 업로드)
- [x] `materialize-problems`에서 문항별 표/그래프/이미지 자산을 `problem_assets`에 upsert 저장
- [x] `GET /ocr/jobs/{job_id}/questions`에 `external_problem_key`, `candidate_index`, `asset_previews` 확장
- [x] `GET /problems` 응답에 자산 목록/미리보기 URL 포함
- [x] 작업목록/문제목록/검수 화면에 시각 자산 썸네일 렌더링 추가
- [x] 검증 완료 (`ruff check`, `python -m compileall`, `pnpm --filter @mathhub/web lint`, `pnpm --filter @mathhub/web build`)

### 27. Mathpix/AI 실시간 상태 반영 강화 — `ce40134`
- [x] 작업 목록 `submit` 버튼 실행 시 Mathpix 제출 직후 자동 sync 폴링으로 완료까지 추적
- [x] `sync` 버튼 동작을 1회 호출에서 완료까지 폴링하는 실시간 모드로 변경
- [x] OCR sync 루프 중 행 상태(`status`, `progress_pct`, `error_message`)를 즉시 갱신
- [x] AI classify 루프 중 행 상태(`ai_done`, `ai_processed/total`, provider/model)를 즉시 갱신
- [x] 진행 중 작업이 있으면 2.5초 간격 백그라운드 무소음 polling으로 목록 자동 최신화
- [x] 검증 완료 (`pnpm --filter @mathhub/web lint`, `pnpm --filter @mathhub/web build`)

### 28. 수식 lim 배치/문항 시각요소 동시 렌더링 보강 — `566a0fd`
- [x] `\lim_{...}` 패턴을 `\lim\limits_{...}`로 정규화해 아래첨자 렌더링 강제
- [x] 본문 내 이미지 문법(`![...](url)`, `<img src=...>`, `\includegraphics{...}`) 파싱 및 표시 추가
- [x] 문항 본문 + 자산 썸네일을 하나의 렌더러(`ProblemStatementView`)로 통합
- [x] 작업목록 문항 미리보기에서 그래프/그림을 본문과 함께 표시하도록 교체
- [x] 검수 화면에서 문제 본문과 그래프/그림을 한 카드 내 동시 표시로 교체
- [x] 시각요소 감지/추출 상태 안내 문구 개선(미추출 시 재적재 가이드)
- [x] 검증 완료 (`pnpm --filter @mathhub/web lint`, `pnpm --filter @mathhub/web build`)

### 29. 2단 문항구조 인식 + 문항별 그래프 자산 분리 저장 — `8330bd4`
- [x] OCR `raw_payload.lines`의 `column/multiple_choice_block/chart` 구조를 이용해 2단 문항 후보 추출 로직 추가
- [x] 후보별 bbox/레이아웃 메타(`split_strategy`, `layout_column`, `layout_mode`)를 AI 분류 결과에 저장
- [x] 시각 자산 힌트를 후보 bbox와의 교집합 기준으로 필터링해 문항별 그래프 귀속 정확도 개선
- [x] `materialize-problems`에서 기존 bbox 없는 후보도 레이아웃 재추출 fallback으로 candidate bbox 보강
- [x] `chart/cnt/region` 좌표 파싱을 bbox 정규화(`x1,y1,x2,y2`)로 통일
- [x] 검증 완료 (`ruff check`, `python -m compileall`, `pnpm --filter @mathhub/web lint`, `pnpm --filter @mathhub/web build`)

### 30. OCR 시각요소/그래프 인식 정확도 개선 — `c2a2114`
- [x] Mathpix submit payload에 `include_diagram_text` 기본 활성화 및 요청 스키마 반영
- [x] sync 완료 시 `lines.json` 항상 반영 + status/lines 페이지 병합으로 raw payload 보존 강화
- [x] line `type/subtype` 기반 그래프 힌트 강화 및 토큰 확장
- [x] bbox에 source page dims 메타를 포함하고 자산 추출 시 좌표계 스케일 보정 로직 개선
- [x] 검증 수행 (`ruff check`, `python -m compileall`, 함수 스모크 테스트)

### 31. inline 이미지 단일화 + 그래프 OCR 잡음 제거 — `a265800`
- [x] 문항 후보 추출 시 그래프/도표/이미지 노드 텍스트를 본문 조합에서 제외
- [x] layout fallback 경로에서도 비주얼 노드를 제외한 텍스트를 우선 사용하도록 보강
- [x] 문항 렌더러를 inline 이미지 방식으로 단일화(기존 별도 시각요소 그리드 제거)
- [x] 이미지가 있는 문항에서 축 라벨/눈금 숫자(`x`,`y`,`1`,`2`,`y=f(x)` 등) 잡음 라인 제거 휴리스틱 추가
- [x] 검증 수행 (`api ruff`, `api compileall`, `web lint`, `web build`, 스모크 테스트)

### 32. 미리보기 선자산 추출 + AI 선택형 적재 지원 — `b105da1`
- [x] `GET /ocr/jobs/{job_id}/questions`에서 `problem_assets`가 없어도 원본 PDF 기준 시각자산을 선추출하여 `asset_previews` 제공
- [x] 선추출 자산은 `ocr-preview-assets` prefix로 S3에 저장하고 presigned URL로 즉시 미리보기 제공
- [x] `materialize-problems`가 AI 분류 결과가 없어도 OCR 후보 + 휴리스틱 분류로 문제를 적재하도록 확장
- [x] AI 미실행 적재 문항은 `metadata.ingest.source=ocr_heuristic_materialize`로 기록해 AI 필터와 분리
- [x] 검증 수행 (`api ruff`, `api compileall`, `web lint`, `web build`, 실 API 호출 검증)
