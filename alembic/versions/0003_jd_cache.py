"""cache extracted JD requirements

Revision ID: 0003_jd_cache
Revises: 0002_agent_output
Create Date: 2026-03-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_jd_cache"
down_revision = "0002_agent_output"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jd_cache",
        sa.Column("jd_url", sa.Text, primary_key=True),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("requirements_jsonb", postgresql.JSONB, nullable=False),
        sa.Column("last_fetched_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("jd_cache")
