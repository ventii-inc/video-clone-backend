"""Add progress tracking to video_models

Revision ID: 9c4d0e1f2a3b
Revises: 8b3c9d0e2f1a
Create Date: 2026-01-22 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c4d0e1f2a3b'
down_revision: Union[str, None] = '8b3c9d0e2f1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('video_models', sa.Column('progress_percent', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('video_models', sa.Column('processing_stage', sa.String(length=20), nullable=False, server_default='pending'))


def downgrade() -> None:
    op.drop_column('video_models', 'processing_stage')
    op.drop_column('video_models', 'progress_percent')
