"""Add visibility column to voice_models

Revision ID: 7a2b8c9d0e1f
Revises: 9c3f47d82a1b
Create Date: 2026-01-22 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a2b8c9d0e1f'
down_revision: Union[str, None] = '9c3f47d82a1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('voice_models', sa.Column('visibility', sa.String(length=20), nullable=False, server_default='private'))


def downgrade() -> None:
    op.drop_column('voice_models', 'visibility')
