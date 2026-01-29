"""Add thumbnail_key to video_models

Revision ID: 9c3f47d82a1b
Revises: 806a539edfe6
Create Date: 2026-01-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c3f47d82a1b'
down_revision: Union[str, None] = '806a539edfe6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('video_models', sa.Column('thumbnail_key', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('video_models', 'thumbnail_key')
