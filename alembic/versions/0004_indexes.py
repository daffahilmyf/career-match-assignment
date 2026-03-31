"""add indexes for scale

Revision ID: 0004_indexes
Revises: 0003_jd_cache
Create Date: 2026-03-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_indexes"
down_revision = "0003_jd_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_match_jobs_status_next_run",
        "match_jobs",
        ["status", "next_run_at"],
    )
    op.create_index(
        "idx_match_jobs_candidate_created",
        "match_jobs",
        ["candidate_id", "created_at"],
    )
    op.create_index(
        "idx_match_jobs_output_gin",
        "match_jobs",
        ["agent_output_jsonb"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_jd_cache_expires_at",
        "jd_cache",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_jd_cache_expires_at", table_name="jd_cache")
    op.drop_index("idx_match_jobs_output_gin", table_name="match_jobs")
    op.drop_index("idx_match_jobs_candidate_created", table_name="match_jobs")
    op.drop_index("idx_match_jobs_status_next_run", table_name="match_jobs")
