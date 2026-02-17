-- Seed for CSAT 2027 math taxonomy
-- Source basis:
-- 1) MOE press release (2024-08-16) + attachment #2:
--    math domain = 30 questions, 2/3/4 points, 100 points, 100 minutes,
--    common(suhak I/II) + elective(probability&statistics/calculus/geometry).
-- 2) Unit depth-2 names follow widely used high-school textbook chapter grouping.

INSERT INTO curriculum_versions (code, name_ko, description, effective_from, effective_to)
VALUES (
    'CSAT_2027',
    '2027학년도 수능 수학 체계',
    '2022학년도부터 적용된 공통+선택 수능 수학 체계(2027학년도 동일 적용)',
    DATE '2022-03-01',
    DATE '2027-11-19'
)
ON CONFLICT (code) DO UPDATE
SET
    name_ko = EXCLUDED.name_ko,
    description = EXCLUDED.description,
    effective_from = EXCLUDED.effective_from,
    effective_to = EXCLUDED.effective_to;

INSERT INTO difficulty_points (point_value, label_ko)
VALUES
    (2, '기본 문항'),
    (3, '중간 문항'),
    (4, '고난도 문항')
ON CONFLICT (point_value) DO UPDATE
SET label_ko = EXCLUDED.label_ko;

WITH cv AS (
    SELECT id FROM curriculum_versions WHERE code = 'CSAT_2027'
)
INSERT INTO exam_blueprints (
    curriculum_version_id,
    name,
    total_questions,
    total_score,
    duration_minutes,
    common_question_ratio,
    elective_question_ratio,
    short_answer_ratio,
    notes
)
SELECT
    cv.id,
    'CSAT_MATH_STANDARD',
    30,
    100,
    100,
    0.750,
    0.250,
    0.300,
    '2027학년도 수능 수학 영역 운영 지표'
FROM cv
ON CONFLICT (curriculum_version_id, name) DO UPDATE
SET
    total_questions = EXCLUDED.total_questions,
    total_score = EXCLUDED.total_score,
    duration_minutes = EXCLUDED.duration_minutes,
    common_question_ratio = EXCLUDED.common_question_ratio,
    elective_question_ratio = EXCLUDED.elective_question_ratio,
    short_answer_ratio = EXCLUDED.short_answer_ratio,
    notes = EXCLUDED.notes;

WITH bp AS (
    SELECT id FROM exam_blueprints
    WHERE name = 'CSAT_MATH_STANDARD'
      AND curriculum_version_id = (SELECT id FROM curriculum_versions WHERE code = 'CSAT_2027')
)
INSERT INTO exam_blueprint_points (blueprint_id, point_value)
SELECT bp.id, v.point_value
FROM bp
CROSS JOIN (VALUES (2), (3), (4)) AS v(point_value)
ON CONFLICT (blueprint_id, point_value) DO NOTHING;

WITH cv AS (
    SELECT id FROM curriculum_versions WHERE code = 'CSAT_2027'
), subject_seed AS (
    SELECT
        cv.id AS curriculum_version_id,
        v.code,
        v.name_ko,
        v.role::math_subject_role AS role,
        v.display_order
    FROM cv
    CROSS JOIN (
        VALUES
            ('MATH_I', '수학Ⅰ', 'common', 1),
            ('MATH_II', '수학Ⅱ', 'common', 2),
            ('PROB_STATS', '확률과 통계', 'elective', 3),
            ('CALCULUS', '미적분', 'elective', 4),
            ('GEOMETRY', '기하', 'elective', 5)
    ) AS v(code, name_ko, role, display_order)
)
INSERT INTO math_subjects (curriculum_version_id, code, name_ko, role, display_order)
SELECT
    curriculum_version_id,
    code,
    name_ko,
    role,
    display_order
FROM subject_seed
ON CONFLICT (curriculum_version_id, code) DO UPDATE
SET
    name_ko = EXCLUDED.name_ko,
    role = EXCLUDED.role,
    display_order = EXCLUDED.display_order,
    is_active = TRUE;

WITH units AS (
    SELECT
        s.id AS subject_id,
        v.code,
        v.name_ko,
        v.display_order,
        v.is_leaf
    FROM math_subjects s
    JOIN curriculum_versions cv ON cv.id = s.curriculum_version_id
    JOIN (
        VALUES
            ('MATH_I', 'EXP_LOG_FUN', '지수함수와 로그함수', 1, FALSE),
            ('MATH_I', 'TRIG_FUNCTION', '삼각함수', 2, FALSE),
            ('MATH_I', 'SEQUENCE', '수열', 3, FALSE),
            ('MATH_II', 'LIMIT_CONT', '함수의 극한과 연속', 1, FALSE),
            ('MATH_II', 'DIFFERENTIATION', '미분', 2, FALSE),
            ('MATH_II', 'INTEGRATION', '적분', 3, FALSE),
            ('PROB_STATS', 'COUNTING', '경우의 수', 1, FALSE),
            ('PROB_STATS', 'PROBABILITY', '확률', 2, FALSE),
            ('PROB_STATS', 'STATISTICS', '통계', 3, FALSE),
            ('CALCULUS', 'SEQ_LIMIT', '수열의 극한', 1, FALSE),
            ('CALCULUS', 'CALC_DIFF', '미분법', 2, FALSE),
            ('CALCULUS', 'CALC_INT', '적분법', 3, FALSE),
            ('GEOMETRY', 'CONIC_SECTIONS', '이차곡선', 1, FALSE),
            ('GEOMETRY', 'PLANE_VECTOR', '평면벡터', 2, FALSE),
            ('GEOMETRY', 'SPACE_GEOMETRY', '공간도형과 공간좌표', 3, FALSE)
    ) AS v(subject_code, code, name_ko, display_order, is_leaf)
      ON s.code = v.subject_code
    WHERE cv.code = 'CSAT_2027'
)
INSERT INTO math_units (
    subject_id,
    parent_unit_id,
    code,
    name_ko,
    depth,
    display_order,
    is_leaf
)
SELECT
    subject_id,
    NULL,
    code,
    name_ko,
    1,
    display_order,
    is_leaf
FROM units
ON CONFLICT (subject_id, code) DO UPDATE
SET
    parent_unit_id = EXCLUDED.parent_unit_id,
    name_ko = EXCLUDED.name_ko,
    depth = EXCLUDED.depth,
    display_order = EXCLUDED.display_order,
    is_leaf = EXCLUDED.is_leaf;

WITH units AS (
    SELECT
        s.id AS subject_id,
        p.id AS parent_unit_id,
        v.code,
        v.name_ko,
        v.display_order
    FROM math_subjects s
    JOIN curriculum_versions cv ON cv.id = s.curriculum_version_id
    JOIN (
        VALUES
            ('MATH_I', 'EXP_LOG_FUN', 'EXP_LOG_BASICS', '거듭제곱과 로그', 1),
            ('MATH_I', 'EXP_LOG_FUN', 'EXP_LOG_PROPERTIES', '지수함수·로그함수의 성질', 2),
            ('MATH_I', 'EXP_LOG_FUN', 'EXP_LOG_APPLICATION', '지수함수·로그함수 활용', 3),
            ('MATH_I', 'TRIG_FUNCTION', 'TRIG_BASICS', '삼각함수의 뜻과 성질', 1),
            ('MATH_I', 'TRIG_FUNCTION', 'TRIG_GRAPH', '삼각함수의 그래프', 2),
            ('MATH_I', 'TRIG_FUNCTION', 'TRIG_APPLICATION', '삼각함수의 활용', 3),
            ('MATH_I', 'SEQUENCE', 'SEQ_ARITH_GEO', '등차수열과 등비수열', 1),
            ('MATH_I', 'SEQUENCE', 'SEQ_SUM', '수열의 합', 2),
            ('MATH_I', 'SEQUENCE', 'SEQ_INDUCTION', '수학적 귀납법', 3),
            ('MATH_II', 'LIMIT_CONT', 'LIMIT_FUNCTION', '함수의 극한', 1),
            ('MATH_II', 'LIMIT_CONT', 'CONTINUITY_FUNCTION', '함수의 연속', 2),
            ('MATH_II', 'DIFFERENTIATION', 'DIFF_DERIVATIVE', '미분계수와 도함수', 1),
            ('MATH_II', 'DIFFERENTIATION', 'DIFF_APPLICATION', '도함수의 활용', 2),
            ('MATH_II', 'INTEGRATION', 'INT_INDEFINITE', '부정적분', 1),
            ('MATH_II', 'INTEGRATION', 'INT_DEFINITE', '정적분', 2),
            ('MATH_II', 'INTEGRATION', 'INT_APPLICATION', '정적분의 활용', 3),
            ('PROB_STATS', 'COUNTING', 'COUNT_PERM_COMB', '순열과 조합', 1),
            ('PROB_STATS', 'COUNTING', 'COUNT_BINOMIAL', '이항정리', 2),
            ('PROB_STATS', 'PROBABILITY', 'PROB_BASIC', '확률의 뜻과 활용', 1),
            ('PROB_STATS', 'PROBABILITY', 'PROB_CONDITIONAL', '조건부확률', 2),
            ('PROB_STATS', 'STATISTICS', 'STAT_DISTRIBUTION', '확률분포', 1),
            ('PROB_STATS', 'STATISTICS', 'STAT_INFERENCE', '통계적 추정', 2),
            ('CALCULUS', 'SEQ_LIMIT', 'CALC_SEQ_LIMIT', '수열의 극한', 1),
            ('CALCULUS', 'SEQ_LIMIT', 'CALC_SERIES', '급수', 2),
            ('CALCULUS', 'CALC_DIFF', 'CALC_DIFF_BASIC', '여러 가지 미분법', 1),
            ('CALCULUS', 'CALC_DIFF', 'CALC_DIFF_APPLICATION', '도함수의 활용', 2),
            ('CALCULUS', 'CALC_INT', 'CALC_INT_BASIC', '여러 가지 적분법', 1),
            ('CALCULUS', 'CALC_INT', 'CALC_INT_APPLICATION', '적분의 활용', 2),
            ('GEOMETRY', 'CONIC_SECTIONS', 'CONIC_PARABOLA', '포물선', 1),
            ('GEOMETRY', 'CONIC_SECTIONS', 'CONIC_ELLIPSE', '타원', 2),
            ('GEOMETRY', 'CONIC_SECTIONS', 'CONIC_HYPERBOLA', '쌍곡선', 3),
            ('GEOMETRY', 'PLANE_VECTOR', 'VECTOR_OPERATION', '벡터의 연산', 1),
            ('GEOMETRY', 'PLANE_VECTOR', 'VECTOR_EQUATION', '직선과 원의 방정식', 2),
            ('GEOMETRY', 'SPACE_GEOMETRY', 'SPACE_FIGURE', '공간도형', 1),
            ('GEOMETRY', 'SPACE_GEOMETRY', 'SPACE_COORDINATE', '공간좌표', 2)
    ) AS v(subject_code, parent_code, code, name_ko, display_order)
      ON s.code = v.subject_code
    JOIN math_units p
      ON p.subject_id = s.id
     AND p.code = v.parent_code
     AND p.depth = 1
    WHERE cv.code = 'CSAT_2027'
)
INSERT INTO math_units (
    subject_id,
    parent_unit_id,
    code,
    name_ko,
    depth,
    display_order,
    is_leaf
)
SELECT
    subject_id,
    parent_unit_id,
    code,
    name_ko,
    2,
    display_order,
    TRUE
FROM units
ON CONFLICT (subject_id, code) DO UPDATE
SET
    parent_unit_id = EXCLUDED.parent_unit_id,
    name_ko = EXCLUDED.name_ko,
    depth = EXCLUDED.depth,
    display_order = EXCLUDED.display_order,
    is_leaf = EXCLUDED.is_leaf;
