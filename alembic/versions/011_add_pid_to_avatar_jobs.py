"""Add pid and output_file to avatar_jobs for detached process tracking

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-23 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add pid column for tracking detached subprocess
    op.add_column('avatar_jobs', sa.Column('pid', sa.Integer(), nullable=True))
    # Add output_file column for tracking stdout/stderr output file path
    op.add_column('avatar_jobs', sa.Column('output_file', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('avatar_jobs', 'output_file')
    op.drop_column('avatar_jobs', 'pid')
