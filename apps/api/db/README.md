# MathHub DB (CSAT 2027 Math + OCR)

## 목적
- Mathpix OCR 결과를 안전하게 보관한다.
- 고등학교 수학 문제를 `2027학년도 수능 체계` 기준으로 분류한다.
- 문제 난이도(배점)를 `2점/3점/4점`으로 저장한다.

## 스키마 파일
- `schema.sql`: 테이블/타입/인덱스/트리거 생성
- `seed_csat_2027_math.sql`: 2027 수능 수학 기준값(과목/단원/배점/블루프린트) 시드

## 핵심 테이블
- `ocr_documents`, `ocr_jobs`, `ocr_pages`: Mathpix OCR 파이프라인 저장
- `curriculum_versions`, `math_subjects`, `math_units`: 수능 체계 및 단원 트리
- `difficulty_points`: 문제 배점(2,3,4)
- `exam_blueprints`, `exam_blueprint_points`: 2027 수능 수학 운영 규칙(문항 수, 공통/선택 비율, 단답형 비율)
- `problem_sources`: 출처 분류/메타데이터(기출문제/연계교재/기타 + 세부타입)
- `problems`, `problem_choices`, `problem_unit_map`, `problem_assets`, `problem_revisions`: 문제은행 본체

## 문제 출처 분류 권장안
- 상위분류(`problem_sources.source_category`)
  - `past_exam`: 기출문제
  - `linked_textbook`: 연계교재
  - `other`: 기타
- 세부분류(`problem_sources.source_type`)
  - `past_exam`: `csat`, `kice_mock`, `office_mock`
  - `linked_textbook`: `ebs_linked`
  - `other`: `private_mock`, `workbook`, `school_exam`, `teacher_made`, `other`
- 문항 단위 식별(`problems`)
  - `source_problem_no`: 숫자 문항 번호(예: 22번)
  - `source_problem_label`: 비정형 문항 표기(예: 유형 2-3, 실전 1회 15번)
- 연도 필드 권장 사용
  - `academic_year`: 학년도(예: 2027학년도)
  - `exam_year`/`exam_month`: 실제 시행 연월(예: 2026-11)

## 2027 기준 반영 내용
- 수학 영역: 30문항, 100점, 100분
- 문항 배점: 2/3/4점
- 출제 범위: 공통(수학Ⅰ, 수학Ⅱ) + 선택(확률과 통계, 미적분, 기하)
- 단답형 30% 포함

## 실행 방법
```bash
# 1) 스키마 생성
psql "$DATABASE_URL" -f apps/api/db/schema.sql

# 2) 2027 수능 수학 기준 시드
psql "$DATABASE_URL" -f apps/api/db/seed_csat_2027_math.sql
```

## 마이그레이션(Alembic)
```bash
cd apps/api

# 현재 리비전 확인
.venv/bin/alembic current

# 최신 스키마 반영
.venv/bin/alembic upgrade head

# 1단계 롤백
.venv/bin/alembic downgrade -1

# 새 리비전 생성
.venv/bin/alembic revision -m "describe_change"
```

- 기본 연결 주소: `postgresql+psycopg://mathhub:mathhub_dev@localhost:5432/mathhub`
- `DATABASE_URL` 환경변수를 주면 해당 주소를 우선 사용합니다.
- baseline 리비전은 고정 스냅샷 파일(`apps/api/migrations/sql/d23823e2de6d_baseline_schema.sql`)을 실행합니다.

## 참고(공식 근거)
- 교육부 보도자료(2024-08-16): 2027학년도 수능 일정/체제 공지
  - https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=294&boardSeq=100526&lev=0&m=020402&opType=N&page=1&s=moe&searchType=null&statusYN=W
- 교육부 보도자료(붙임2): 2027학년도 영역별 문항 유형·배점·출제범위
  - 위 보도자료 첨부문서(동일 페이지)
- 교육부 보도자료(2025-06-02): 2028학년도부터 통합형(선택과목 폐지) 적용
  - https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=294&boardSeq=103512&lev=0&m=020402&opType=N&page=1&s=moe&searchType=null&statusYN=W
- 한국교육과정평가원 수능 사이트: 기출문제 메뉴에서 `대학수학능력시험`/`수능 모의평가` 분리
  - https://www.suneung.re.kr/main.do?s=suneung
  - https://www.suneung.re.kr/boardCnts/list.do?boardID=1500285&m=030502&s=suneung
- EBSi: `2027 수능 대비 필수 연계교재` 안내
  - https://www.ebsi.co.kr/
- 서울특별시교육청: 전국연합학력평가 안내(시도교육청 학평 축)
  - https://www.sen.go.kr/
- 일반 문항검색 플랫폼 참고(분류/필터 패턴)
  - https://www.mathflat.com/pricing
  - https://thub.kumsung.co.kr/

## Assumption
- `math_units`의 2단계 단원(중단원)은 수능 출제과목의 교과서 공통 대단원/중단원 관행을 기반으로 한 운영 taxonomy다.
- 실제 서비스 운영 시 학교/교재 단원 체계가 다르면 `math_units`를 추가/수정해 맞춘다.
