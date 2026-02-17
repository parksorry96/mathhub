-- MathHub Postgres schema
-- Scope: OCR(Mathpix) -> high-school math problem bank -> CSAT(2027) taxonomy

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    CREATE TYPE ocr_job_status AS ENUM (
        'queued',
        'uploading',
        'processing',
        'completed',
        'failed',
        'cancelled'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
    CREATE TYPE math_subject_role AS ENUM ('common', 'elective');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
    CREATE TYPE problem_response_type AS ENUM ('five_choice', 'short_answer');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
    CREATE TYPE problem_source_category AS ENUM ('past_exam', 'linked_textbook', 'other');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
    CREATE TYPE problem_source_type AS ENUM (
        'csat',
        'kice_mock',
        'office_mock',
        'ebs_linked',
        'private_mock',
        'workbook',
        'school_exam',
        'teacher_made',
        'other'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
    CREATE TYPE problem_asset_type AS ENUM ('image', 'table', 'graph', 'other');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

CREATE TABLE IF NOT EXISTS curriculum_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL UNIQUE,
    name_ko TEXT NOT NULL,
    description TEXT,
    effective_from DATE,
    effective_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS math_subjects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    curriculum_version_id UUID NOT NULL REFERENCES curriculum_versions(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name_ko TEXT NOT NULL,
    role math_subject_role NOT NULL,
    display_order SMALLINT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (curriculum_version_id, code),
    UNIQUE (curriculum_version_id, id)
);

CREATE TABLE IF NOT EXISTS math_units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL REFERENCES math_subjects(id) ON DELETE CASCADE,
    parent_unit_id UUID REFERENCES math_units(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name_ko TEXT NOT NULL,
    depth SMALLINT NOT NULL CHECK (depth BETWEEN 1 AND 3),
    display_order SMALLINT NOT NULL,
    is_leaf BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (subject_id, code),
    UNIQUE (subject_id, parent_unit_id, display_order)
);

CREATE TABLE IF NOT EXISTS difficulty_points (
    point_value SMALLINT PRIMARY KEY,
    label_ko TEXT NOT NULL,
    CHECK (point_value IN (2, 3, 4))
);

CREATE TABLE IF NOT EXISTS exam_blueprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    curriculum_version_id UUID NOT NULL REFERENCES curriculum_versions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    total_questions SMALLINT NOT NULL CHECK (total_questions > 0),
    total_score SMALLINT NOT NULL CHECK (total_score > 0),
    duration_minutes SMALLINT NOT NULL CHECK (duration_minutes > 0),
    common_question_ratio NUMERIC(4, 3) NOT NULL CHECK (common_question_ratio >= 0 AND common_question_ratio <= 1),
    elective_question_ratio NUMERIC(4, 3) NOT NULL CHECK (elective_question_ratio >= 0 AND elective_question_ratio <= 1),
    short_answer_ratio NUMERIC(4, 3) NOT NULL CHECK (short_answer_ratio >= 0 AND short_answer_ratio <= 1),
    notes TEXT,
    UNIQUE (curriculum_version_id, name),
    CHECK ((common_question_ratio + elective_question_ratio) <= 1.000)
);

CREATE TABLE IF NOT EXISTS exam_blueprint_points (
    blueprint_id UUID NOT NULL REFERENCES exam_blueprints(id) ON DELETE CASCADE,
    point_value SMALLINT NOT NULL REFERENCES difficulty_points(point_value),
    PRIMARY KEY (blueprint_id, point_value)
);

CREATE TABLE IF NOT EXISTS problem_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_code TEXT UNIQUE,
    source_category problem_source_category NOT NULL,
    source_type problem_source_type NOT NULL,
    title TEXT NOT NULL,
    organization TEXT,
    publisher TEXT,
    academic_year SMALLINT CHECK (academic_year BETWEEN 2000 AND 2100),
    exam_year SMALLINT CHECK (exam_year BETWEEN 2000 AND 2100),
    exam_month SMALLINT CHECK (exam_month BETWEEN 1 AND 12),
    exam_session TEXT,
    grade_level SMALLINT CHECK (grade_level BETWEEN 1 AND 3),
    series_name TEXT,
    volume_label TEXT,
    source_url TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (source_category = 'past_exam' AND source_type IN ('csat', 'kice_mock', 'office_mock'))
        OR (source_category = 'linked_textbook' AND source_type = 'ebs_linked')
        OR (source_category = 'other' AND source_type IN ('private_mock', 'workbook', 'school_exam', 'teacher_made', 'other'))
    )
);

CREATE TABLE IF NOT EXISTS ocr_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    storage_key TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes > 0),
    sha256 TEXT NOT NULL UNIQUE CHECK (sha256 ~ '^[a-fA-F0-9]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ocr_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES ocr_documents(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'mathpix',
    provider_job_id TEXT UNIQUE,
    status ocr_job_status NOT NULL DEFAULT 'queued',
    progress_pct NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (progress_pct >= 0 AND progress_pct <= 100),
    error_code TEXT,
    error_message TEXT,
    raw_response JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    CHECK (finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at))
);

CREATE TABLE IF NOT EXISTS ocr_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES ocr_jobs(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL CHECK (page_no > 0),
    status ocr_job_status NOT NULL DEFAULT 'processing',
    extracted_text TEXT,
    extracted_latex TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id, page_no)
);

CREATE TABLE IF NOT EXISTS problems (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    curriculum_version_id UUID NOT NULL REFERENCES curriculum_versions(id) ON DELETE RESTRICT,
    source_id UUID REFERENCES problem_sources(id) ON DELETE SET NULL,
    ocr_page_id UUID REFERENCES ocr_pages(id) ON DELETE SET NULL,
    external_problem_key TEXT,
    primary_subject_id UUID NOT NULL,
    response_type problem_response_type NOT NULL,
    point_value SMALLINT NOT NULL REFERENCES difficulty_points(point_value),
    answer_key TEXT NOT NULL,
    source_problem_no SMALLINT CHECK (source_problem_no > 0),
    source_problem_label TEXT,
    problem_text_raw TEXT,
    problem_text_latex TEXT,
    problem_text_final TEXT,
    solution_text TEXT,
    explanation_text TEXT,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    verified_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (external_problem_key),
    CHECK (
        (response_type = 'five_choice' AND answer_key ~ '^[1-5]$')
        OR (response_type = 'short_answer' AND length(trim(answer_key)) > 0)
    ),
    FOREIGN KEY (curriculum_version_id, primary_subject_id)
        REFERENCES math_subjects(curriculum_version_id, id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS problem_choices (
    problem_id UUID NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    choice_no SMALLINT NOT NULL CHECK (choice_no BETWEEN 1 AND 5),
    choice_text TEXT,
    choice_latex TEXT,
    PRIMARY KEY (problem_id, choice_no)
);

CREATE TABLE IF NOT EXISTS problem_unit_map (
    problem_id UUID NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    unit_id UUID NOT NULL REFERENCES math_units(id) ON DELETE RESTRICT,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (problem_id, unit_id)
);

CREATE TABLE IF NOT EXISTS problem_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    problem_id UUID NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    asset_type problem_asset_type NOT NULL,
    storage_key TEXT NOT NULL,
    page_no INTEGER CHECK (page_no > 0),
    bbox JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (problem_id, storage_key)
);

CREATE TABLE IF NOT EXISTS problem_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    problem_id UUID NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    revision_no INTEGER NOT NULL CHECK (revision_no > 0),
    editor_note TEXT,
    snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (problem_id, revision_no)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_problem_primary_unit
    ON problem_unit_map (problem_id)
    WHERE is_primary = TRUE;

CREATE INDEX IF NOT EXISTS idx_math_units_subject_parent
    ON math_units (subject_id, parent_unit_id, display_order);

CREATE INDEX IF NOT EXISTS idx_ocr_jobs_status_requested
    ON ocr_jobs (status, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_ocr_pages_job_page
    ON ocr_pages (job_id, page_no);

CREATE INDEX IF NOT EXISTS idx_problems_subject_point
    ON problems (primary_subject_id, point_value);

CREATE INDEX IF NOT EXISTS idx_problems_verified_created
    ON problems (is_verified, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_problems_source
    ON problems (source_id, source_problem_no);

CREATE UNIQUE INDEX IF NOT EXISTS uq_problems_source_problem_no
    ON problems (source_id, source_problem_no)
    WHERE source_id IS NOT NULL AND source_problem_no IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_problem_sources_category_type
    ON problem_sources (source_category, source_type, academic_year, exam_year);

CREATE INDEX IF NOT EXISTS idx_problem_unit_map_unit
    ON problem_unit_map (unit_id);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_ocr_pages_updated_at ON ocr_pages;
CREATE TRIGGER tr_ocr_pages_updated_at
BEFORE UPDATE ON ocr_pages
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS tr_problems_updated_at ON problems;
CREATE TRIGGER tr_problems_updated_at
BEFORE UPDATE ON problems
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
