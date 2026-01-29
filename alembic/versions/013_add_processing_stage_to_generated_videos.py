"""Add processing_stage to generated_videos

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-01-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('generated_videos', sa.Column('processing_stage', sa.String(length=20), nullable=False, server_default='queued'))
    # Update progress_percent to have a default and be non-nullable
    op.alter_column('generated_videos', 'progress_percent',
                    existing_type=sa.Integer(),
                    nullable=False,
                    server_default='0')


def downgrade() -> None:
    op.alter_column('generated_videos', 'progress_percent',
                    existing_type=sa.Integer(),
                    nullable=True,
                    server_default=None)
    op.drop_column('generated_videos', 'processing_stage')
