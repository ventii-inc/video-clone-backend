"""Rename model_data_url to reference_id in voice_models

Revision ID: 012
Revises: 011
Create Date: 2024-01-23

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    # Rename column model_data_url to reference_id
    op.alter_column('voice_models', 'model_data_url', new_column_name='reference_id')

    # Mark mock entries as incomplete
    op.execute("UPDATE voice_models SET status = 'incomplete' WHERE reference_id LIKE 'mock://%'")


def downgrade():
    # Revert status changes
    op.execute("UPDATE voice_models SET status = 'completed' WHERE reference_id LIKE 'mock://%'")

    # Rename column back
    op.alter_column('voice_models', 'reference_id', new_column_name='model_data_url')
