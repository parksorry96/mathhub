"""baseline_schema

Revision ID: d23823e2de6d
Revises: 
Create Date: 2026-02-18 00:20:02.581227

"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd23823e2de6d'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "sql"
        / "d23823e2de6d_baseline_schema.sql"
    )
    schema_sql = schema_path.read_text(encoding="utf-8")
    bind = op.get_bind()
    raw_connection = bind.connection
    with raw_connection.cursor() as cursor:
        cursor.execute(schema_sql)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    raw_connection = bind.connection
    with raw_connection.cursor() as cursor:
        cursor.execute(
            """
            DROP TRIGGER IF EXISTS tr_problems_updated_at ON problems;
            DROP TRIGGER IF EXISTS tr_ocr_pages_updated_at ON ocr_pages;
            DROP FUNCTION IF EXISTS set_updated_at();

            DROP TABLE IF EXISTS problem_revisions CASCADE;
            DROP TABLE IF EXISTS problem_assets CASCADE;
            DROP TABLE IF EXISTS problem_unit_map CASCADE;
            DROP TABLE IF EXISTS problem_choices CASCADE;
            DROP TABLE IF EXISTS problems CASCADE;
            DROP TABLE IF EXISTS ocr_pages CASCADE;
            DROP TABLE IF EXISTS ocr_jobs CASCADE;
            DROP TABLE IF EXISTS ocr_documents CASCADE;
            DROP TABLE IF EXISTS problem_sources CASCADE;
            DROP TABLE IF EXISTS exam_blueprint_points CASCADE;
            DROP TABLE IF EXISTS exam_blueprints CASCADE;
            DROP TABLE IF EXISTS difficulty_points CASCADE;
            DROP TABLE IF EXISTS math_units CASCADE;
            DROP TABLE IF EXISTS math_subjects CASCADE;
            DROP TABLE IF EXISTS curriculum_versions CASCADE;

            DROP TYPE IF EXISTS problem_asset_type;
            DROP TYPE IF EXISTS problem_source_type;
            DROP TYPE IF EXISTS problem_source_category;
            DROP TYPE IF EXISTS problem_response_type;
            DROP TYPE IF EXISTS math_subject_role;
            DROP TYPE IF EXISTS ocr_job_status;
            """
        )
