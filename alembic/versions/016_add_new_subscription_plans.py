"""Add new subscription plans: Shot plan, training limits, abuse prevention

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-01-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to subscriptions table
    op.add_column('subscriptions', sa.Column('monthly_video_training_limit', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('subscriptions', sa.Column('monthly_voice_training_limit', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('subscriptions', sa.Column('is_one_time_purchase', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('subscriptions', sa.Column('is_lifetime', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('subscriptions', sa.Column('auto_charge_enabled', sa.Boolean(), nullable=False, server_default='true'))

    # Create training_usage_records table
    op.create_table('training_usage_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('period_year', sa.Integer(), nullable=False),
        sa.Column('period_month', sa.Integer(), nullable=False),
        sa.Column('base_video_trainings', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('base_voice_trainings', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('used_video_trainings', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('used_voice_trainings', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('additional_video_trainings', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('additional_voice_trainings', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'period_year', 'period_month', name='uq_training_user_period')
    )
    op.create_index(op.f('ix_training_usage_records_user_id'), 'training_usage_records', ['user_id'], unique=False)

    # Create deleted_account_records table for abuse prevention
    op.create_table('deleted_account_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email_hash', sa.String(length=64), nullable=False),
        sa.Column('firebase_uid', sa.String(length=128), nullable=True),
        sa.Column('used_free_plan', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deleted_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deleted_account_records_email_hash'), 'deleted_account_records', ['email_hash'], unique=False)
    op.create_index(op.f('ix_deleted_account_records_firebase_uid'), 'deleted_account_records', ['firebase_uid'], unique=False)

    # Update existing subscriptions data
    # Free users: set is_lifetime=true, update limits
    op.execute("""
        UPDATE subscriptions
        SET is_lifetime = true,
            monthly_video_training_limit = 1,
            monthly_voice_training_limit = 1,
            monthly_minutes_limit = 3,
            auto_charge_enabled = false
        WHERE plan_type = 'free'
    """)

    # Standard users: set appropriate limits
    op.execute("""
        UPDATE subscriptions
        SET monthly_video_training_limit = 5,
            monthly_voice_training_limit = 5,
            auto_charge_enabled = true
        WHERE plan_type = 'standard'
    """)


def downgrade() -> None:
    # Drop deleted_account_records table
    op.drop_index(op.f('ix_deleted_account_records_firebase_uid'), table_name='deleted_account_records')
    op.drop_index(op.f('ix_deleted_account_records_email_hash'), table_name='deleted_account_records')
    op.drop_table('deleted_account_records')

    # Drop training_usage_records table
    op.drop_index(op.f('ix_training_usage_records_user_id'), table_name='training_usage_records')
    op.drop_table('training_usage_records')

    # Remove new columns from subscriptions
    op.drop_column('subscriptions', 'auto_charge_enabled')
    op.drop_column('subscriptions', 'is_lifetime')
    op.drop_column('subscriptions', 'is_one_time_purchase')
    op.drop_column('subscriptions', 'monthly_voice_training_limit')
    op.drop_column('subscriptions', 'monthly_video_training_limit')
