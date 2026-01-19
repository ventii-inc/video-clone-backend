"""Add avatar_jobs table

Revision ID: 004
Revises: 003
Create Date: 2025-01-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create avatar_jobs table
    op.create_table(
        "avatar_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("video_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, default=0),
        sa.Column("max_attempts", sa.Integer(), nullable=False, default=3),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("runpod_job_id", sa.String(100), nullable=True),
        sa.Column("avatar_s3_key", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["video_model_id"], ["video_models.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_avatar_jobs_video_model_id", "avatar_jobs", ["video_model_id"])
    op.create_index("ix_avatar_jobs_user_id", "avatar_jobs", ["user_id"])
    op.create_index("ix_avatar_jobs_status", "avatar_jobs", ["status"])
    op.create_index("ix_avatar_jobs_runpod_job_id", "avatar_jobs", ["runpod_job_id"])


def downgrade() -> None:
    op.drop_index("ix_avatar_jobs_runpod_job_id", table_name="avatar_jobs")
    op.drop_index("ix_avatar_jobs_status", table_name="avatar_jobs")
    op.drop_index("ix_avatar_jobs_user_id", table_name="avatar_jobs")
    op.drop_index("ix_avatar_jobs_video_model_id", table_name="avatar_jobs")
    op.drop_table("avatar_jobs")
