"""Add payment method cache to subscription

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-01-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('subscriptions', sa.Column('card_brand', sa.String(length=20), nullable=True))
    op.add_column('subscriptions', sa.Column('card_last4', sa.String(length=4), nullable=True))
    op.add_column('subscriptions', sa.Column('card_exp_month', sa.SmallInteger(), nullable=True))
    op.add_column('subscriptions', sa.Column('card_exp_year', sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('subscriptions', 'card_exp_year')
    op.drop_column('subscriptions', 'card_exp_month')
    op.drop_column('subscriptions', 'card_last4')
    op.drop_column('subscriptions', 'card_brand')
