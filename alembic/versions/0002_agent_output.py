"""store agent results on jobs

Revision ID: 0002_agent_output
Revises: 0001_initial
Create Date: 2026-03-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_agent_output"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("match_jobs", sa.Column("agent_output_jsonb", postgresql.JSONB, nullable=True))
    op.add_column("match_jobs", sa.Column("agent_trace_jsonb", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("match_jobs", "agent_trace_jsonb")
    op.drop_column("match_jobs", "agent_output_jsonb")
