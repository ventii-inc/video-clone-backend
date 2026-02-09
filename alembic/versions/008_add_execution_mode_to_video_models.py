"""Add execution_mode to video_models

Revision ID: 8b3c9d0e2f1a
Revises: 7a2b8c9d0e1f
Create Date: 2026-01-22 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b3c9d0e2f1a'
down_revision: Union[str, None] = '7a2b8c9d0e1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('video_models', sa.Column('execution_mode', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('video_models', 'execution_mode')
