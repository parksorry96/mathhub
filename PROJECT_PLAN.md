# Math OCR → 문제 DB → 교재/평가 플랫폼 실행 계획

## 1) Work Plan (이 문서 작성 작업)
- [x] AGENTS 규칙 및 현재 워크스페이스 상태 확인
- [x] 공식 문서 기반 사전 조사(Context7 + 1차 출처) 수행
- [x] 딥 분석(아키텍처 경계/실패 모드/검증 목표) 정리
- [x] 단계별 실행 로드맵/백로그 작성
- [x] 셀프 리뷰 수행
- [x] 검증 근거 기록

## 2) Pre-Research (사전 조사 기록)
### Fact
- [x] 워크스페이스는 현재 `/Users/parkjisong/myhub/AGENTS.md` 중심의 초기 상태이며 구현 코드가 아직 없다.
- [x] Mathpix PDF 처리 API는 비동기 방식이며 대용량 문서는 처리에 시간이 걸릴 수 있다.
- [x] Mathpix PDF API는 `streaming=true` 설정 시 SSE 스트림 엔드포인트를 통해 페이지 단위 부분 결과를 받을 수 있다.
- [x] Mathpix는 PDF 처리에서 서버 키(`app_id`, `app_key`) 사용을 권장하며, 클라이언트용 앱 토큰은 PDF 기능 제한이 있다.
- [x] Next.js App Router는 서버 컴포넌트/Route Handler 중심 구성이 권장된다.
- [x] TanStack Query는 Next.js App Router에서 `QueryClientProvider`를 통해 서버 상태 캐싱/무효화 전략을 구성한다.
- [x] MUI는 Next.js App Router에서 `AppRouterCacheProvider` 기반 SSR 스타일 수집 구성을 제공한다.
- [x] FastAPI `BackgroundTasks`는 경량 작업에는 적합하지만, 무거운 작업은 Celery+Redis/RabbitMQ 같은 워커 큐가 권장된다.
- [x] 패키지 매니저: **pnpm** (workspace 기반 모노레포 관리)

### Fact: 영향 범위 (초기 설계)
- [x] 프론트엔드: Next.js(App Router) + React + TypeScript + React Query + MUI
- [x] 백엔드: FastAPI(도메인/비동기 작업) + Next.js(BFF/인증/세션 게이트웨이)
- [x] 데이터: Postgres(정규 데이터), Redis(큐/캐시), 객체 스토리지(S3 호환)
- [x] 외부 연동: Mathpix OCR API

### Assumption
- [x] 초기 사용자는 교사(본인) 중심이며, 멀티 조직/대규모 동시접속은 2차 최적화 대상으로 둔다.
- [x] 교재 PDF는 합법적으로 보유/활용 가능한 자료만 다룬다.
- [x] MVP 단계에서는 문제 분할 자동화 후 수동 검수 워크플로를 반드시 포함한다.

## 3) Deep Analysis (설계 핵심)
### End-to-end 경로
- [x] 업로드 → OCR Job 생성 → Mathpix 처리(비동기/스트리밍) → 문제 분할/정규화 → 검수 → DB 확정 → 교재 편집/출력 → 시험 출제/채점/추천 확장

### 실패 모드 및 리스크
- [x] OCR 품질 편차: 수식/도표/표에서 인식 오류 발생 가능
- [x] 비용 리스크: 대량 PDF 처리 시 API 비용 급증 가능
- [x] 지연 리스크: OCR/후처리 장시간 작업으로 UX 저하
- [x] 저작권/개인정보 리스크: 원본 문서 보관 정책 부재 시 운영 리스크
- [x] 데이터 오염 리스크: 저품질 OCR 결과가 추천/시험 출제까지 전파

### TODO별 검증 목표
- [x] OCR 결과 품질 지표(문항 분할 정확도/수식 정확도/검수 소요시간) 수립
- [x] Job 상태 추적(queued/running/partial/completed/failed) 및 재시도 정책 정의
- [x] 핵심 엔터티 버전 관리(원본/파싱결과/수정본) 설계

## 4) 시스템 아키텍처 제안
## 목표
- [ ] Next.js는 사용자 UI + BFF(인증/권한/요청 집계) 역할
- [ ] FastAPI는 OCR 파이프라인/문항 도메인/비동기 워커 API 역할
- [ ] Job Queue(권장: Celery+Redis 또는 RQ)로 OCR/파싱/추천 연산 분리
- [ ] Postgres를 단일 진실 원천으로 사용, 원본/파생 데이터 계층화

## 서비스 경계
- [ ] `Next.js`: 로그인, 교재 편집 UI, 검수 UI, 시험 생성 UI, 학생 풀이 UI
- [ ] `Next.js Route Handlers`: BFF 라우트, 세션 확인, FastAPI 호출 프록시
- [ ] `FastAPI API`: OCR 작업 생성/상태 조회/문항 CRUD/시험 생성/채점
- [ ] `Worker`: Mathpix 호출, PDF 페이지별 파싱, 유사도 인덱싱, 배치 채점
- [ ] `Storage`: PDF 원본/렌더링 이미지/추출 JSON 아카이빙

## 5) 데이터 모델 (MVP 중심)
- [ ] `users`, `roles`, `classes`, `students`
- [ ] `books` (교재 메타), `book_files` (원본 PDF)
- [ ] `ocr_jobs` (상태/진행률/에러), `ocr_pages` (페이지 단위 결과)
- [ ] `problems` (문항 원본), `problem_versions` (수정/정제 이력)
- [ ] `problem_assets` (이미지/수식/도표)
- [ ] `tags` (단원/난이도/유형), `problem_tag_map`
- [ ] `workbooks`, `workbook_items`
- [ ] `exams`, `exam_items`, `submissions`, `grading_results`
- [ ] `similarity_index` (후속: pgvector 또는 별도 벡터 저장소)

## 6) OCR 파이프라인 설계 (핵심)
### Ingestion
- [ ] PDF 업로드(직접 업로드 또는 URL 등록)
- [ ] `ocr_jobs` 생성, 원본 파일 체크섬/중복 검사
- [ ] FastAPI 워커가 Mathpix PDF API 호출

### Processing
- [ ] Mathpix `pdf_id` 저장 후 상태 폴링 + 필요 시 스트리밍 수신
- [ ] 완료 시 `*.lines.json`, `*.lines.mmd.json` 등 결과 저장
- [ ] 페이지/블록 단위로 문제 후보 분할(번호 패턴 + 레이아웃 규칙)
- [ ] 신뢰도/예외 규칙 기반 검수 큐 생성

### Curation
- [ ] 검수 UI에서 문항 경계/정답/해설/태그 교정
- [ ] 확정 시 `problem_versions`에 승인본 저장
- [ ] 원본-파싱본-수정본 추적 가능하도록 감사 로그 유지

## 7) 제품 기능 로드맵
## Phase 0 (1~2주): 기반 구축
- [ ] 모노레포 초기화(`apps/web`, `apps/api`, `packages/*`)
- [ ] 인증/권한 기본 구조(교사/학생)
- [ ] Postgres/Redis/S3 로컬-스테이징 환경 구성
- [ ] 기본 CI(타입체크+테스트+린트)

## Phase 1 (2~4주): OCR MVP
- [ ] PDF 업로드/작업 생성/상태조회 API
- [ ] Mathpix 연동 + 실패 재시도 + 에러 분류
- [ ] 문항 분할 v1 + 검수 대시보드
- [ ] 문제 검색/필터(단원/난이도/유형)

## Phase 2 (2~3주): 교재 제작
- [ ] 드래그앤드롭 교재 편집기
- [ ] 문항 랜덤화/난이도 밸런싱 규칙
- [ ] PDF/문서 출력(교사용/학생용)

## Phase 3 (3~5주): 시험/채점
- [ ] 시험지 생성/배포/제출 플로우
- [ ] 객관식 자동채점 + 주관식 반자동 채점
- [ ] 오답 분석 리포트(개인/반 단위)

## Phase 4 (3~6주): 유사문제 추천
- [ ] 문항 임베딩 파이프라인
- [ ] 학생 오답 기반 개인화 추천
- [ ] 추천 품질 A/B 테스트

## 8) 프론트엔드 실행 가이드 (Next.js + React Query + MUI)
- [ ] App Router 기준 서버 컴포넌트 기본 + 클라이언트 최소화
- [ ] React Query 키 규칙 통일: `['problems', filters]`, `['ocrJob', jobId]` 등
- [ ] 기본 `staleTime` 설정으로 과도한 재조회 방지
- [ ] MUI `AppRouterCacheProvider` + `ThemeProvider`로 SSR 깜빡임 최소화
- [ ] 대용량 테이블(문항 리스트) 가상화/페이지네이션 적용

## 9) 백엔드 실행 가이드 (FastAPI + Worker)
- [ ] API 계층: 입력 검증(Pydantic) + 서비스 계층 + 리포지토리 계층
- [ ] 비동기 Job API: 생성(202) / 상태조회 / 취소 / 재시도
- [ ] 워커 큐 분리: OCR, 파싱, 추천, 채점 작업을 큐 단위 분리
- [ ] 관측성: 작업 실패율, 평균 처리시간, 재시도 횟수 메트릭 수집

## 10) 검증 지표 (MVP)
- [ ] OCR 성공률(작업 완료율) >= 98%
- [ ] 문항 분할 정확도(샘플 검수 기준) >= 90%
- [ ] 수식 오류율(검수 기준) <= 5%
- [ ] 평균 처리시간(100p PDF 기준) 목표 설정 후 주차별 개선
- [ ] 검수자 1인당 시간/문항 지표 추적

## 11) 운영/보안 체크
- [ ] API 키 서버 보관(클라이언트 노출 금지), 주기적 로테이션
- [ ] 원본 PDF/결과물 보관 주기 및 삭제 정책
- [ ] 접근 로그/감사 로그/권한 분리
- [ ] 저작권 정책 및 사용자 약관 반영

## 12) 첫 스프린트 실제 작업 목록 (바로 시작)
- [ ] 모노레포 생성 및 공통 타입 패키지 준비
- [ ] FastAPI 기본 골격 + 헬스체크 + OCR job 엔드포인트 스켈레톤
- [ ] Next.js 대시보드(업로드/작업상태) 화면 스켈레톤
- [ ] Postgres 스키마 초안(`ocr_jobs`, `ocr_pages`, `problems`) 적용
- [ ] Mathpix 샌드박스 호출 POC 및 저장 파이프라인 1회 성공
- [ ] 검수 UI 초안(페이지별 추출 텍스트 + 문제 경계 수정)

## 13) Review (셀프 리뷰)
- [x] 사용자 지정 스택(React/Next/TS/React Query/MUI + FastAPI)을 모두 반영했는지 확인
- [x] 시작지점(OCR→DB→교재)과 확장지점(시험/채점/추천)을 한 로드맵으로 연결했는지 확인
- [x] 구현 우선순위를 “데이터 품질/추적성/비동기 안정성” 중심으로 정렬했는지 확인

## 14) Validation Evidence
- [x] 문서 근거 확인: Next.js, TanStack Query, FastAPI, MUI, Mathpix 공식 문서 확인
- [x] 로컬 검증: 워크스페이스 파일 구조/문서 존재 상태 확인
- [x] GitHub 연결 상태 확인: 현재 경로는 git repo 아님(커밋/푸시 단계 비대상)

