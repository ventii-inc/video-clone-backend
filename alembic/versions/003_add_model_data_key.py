"""Add model_data_key to video_models

Revision ID: 003
Revises: 002
Create Date: 2025-01-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add model_data_key column to video_models table for storing S3 key of avatar TAR file
    op.add_column(
        "video_models",
        sa.Column("model_data_key", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("video_models", "model_data_key")
