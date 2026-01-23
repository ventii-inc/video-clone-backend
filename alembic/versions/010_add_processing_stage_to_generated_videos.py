"""Add processing_stage to generated_videos

Revision ID: 0a5b6c7d8e9f
Revises: 9c4d0e1f2a3b
Create Date: 2026-01-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a5b6c7d8e9f'
down_revision: Union[str, None] = '9c4d0e1f2a3b'
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
