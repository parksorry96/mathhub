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
- `problems`, `problem_choices`, `problem_unit_map`, `problem_assets`, `problem_revisions`: 문제은행 본체

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

## 참고(공식 근거)
- 교육부 보도자료(2024-08-16): 2027학년도 수능 일정/체제 공지
  - https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=294&boardSeq=100526&lev=0&m=020402&opType=N&page=1&s=moe&searchType=null&statusYN=W
- 교육부 보도자료(붙임2): 2027학년도 영역별 문항 유형·배점·출제범위
  - 위 보도자료 첨부문서(동일 페이지)
- 교육부 보도자료(2025-06-02): 2028학년도부터 통합형(선택과목 폐지) 적용
  - https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=294&boardSeq=103512&lev=0&m=020402&opType=N&page=1&s=moe&searchType=null&statusYN=W

## Assumption
- `math_units`의 2단계 단원(중단원)은 수능 출제과목의 교과서 공통 대단원/중단원 관행을 기반으로 한 운영 taxonomy다.
- 실제 서비스 운영 시 학교/교재 단원 체계가 다르면 `math_units`를 추가/수정해 맞춘다.
