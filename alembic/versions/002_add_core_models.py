"""Add all core models

Revision ID: 002
Revises: 001
Create Date: 2025-01-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add avatar_url to users table
    op.add_column("users", sa.Column("avatar_url", sa.String(500), nullable=True))

    # Create user_profiles table
    op.create_table(
        "user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("usage_type", sa.String(20), nullable=True),
        sa.Column("company_size", sa.String(20), nullable=True),
        sa.Column("role", sa.String(50), nullable=True),
        sa.Column("use_cases", postgresql.JSON(), nullable=True),
        sa.Column("referral_source", sa.String(50), nullable=True),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, default=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )

    # Create user_settings table
    op.create_table(
        "user_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("email_notifications", sa.Boolean(), nullable=False, default=True),
        sa.Column("language", sa.String(10), nullable=False, default="ja"),
        sa.Column("default_resolution", sa.String(10), nullable=False, default="720p"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )

    # Create subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(100), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(100), nullable=True),
        sa.Column("plan_type", sa.String(20), nullable=False, default="free"),
        sa.Column("status", sa.String(20), nullable=False, default="active"),
        sa.Column("monthly_minutes_limit", sa.Integer(), nullable=False, default=0),
        sa.Column("current_period_start", sa.DateTime(), nullable=True),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("canceled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_subscriptions_stripe_customer_id", "subscriptions", ["stripe_customer_id"])
    op.create_index("ix_subscriptions_stripe_subscription_id", "subscriptions", ["stripe_subscription_id"])

    # Create video_models table
    op.create_table(
        "video_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("source_video_url", sa.String(500), nullable=True),
        sa.Column("source_video_key", sa.String(500), nullable=True),
        sa.Column("model_data_url", sa.String(500), nullable=True),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(), nullable=True),
        sa.Column("processing_completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_video_models_user_id", "video_models", ["user_id"])
    op.create_index("ix_video_models_status", "video_models", ["status"])

    # Create voice_models table
    op.create_table(
        "voice_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("source_audio_url", sa.String(500), nullable=True),
        sa.Column("source_audio_key", sa.String(500), nullable=True),
        sa.Column("model_data_url", sa.String(500), nullable=True),
        sa.Column("source_type", sa.String(20), nullable=False, default="upload"),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(), nullable=True),
        sa.Column("processing_completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_voice_models_user_id", "voice_models", ["user_id"])
    op.create_index("ix_voice_models_status", "voice_models", ["status"])

    # Create generated_videos table
    op.create_table(
        "generated_videos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("video_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("voice_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("input_text_language", sa.String(10), nullable=False, default="ja"),
        sa.Column("output_video_url", sa.String(500), nullable=True),
        sa.Column("output_video_key", sa.String(500), nullable=True),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
        sa.Column("resolution", sa.String(10), nullable=False, default="720p"),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("credits_used", sa.Integer(), nullable=False, default=0),
        sa.Column("status", sa.String(20), nullable=False, default="queued"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queue_position", sa.Integer(), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(), nullable=True),
        sa.Column("processing_completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_model_id"], ["video_models.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["voice_model_id"], ["voice_models.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_generated_videos_user_id", "generated_videos", ["user_id"])
    op.create_index("ix_generated_videos_status", "generated_videos", ["status"])

    # Create usage_records table
    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("base_minutes", sa.Integer(), nullable=False, default=0),
        sa.Column("used_minutes", sa.Integer(), nullable=False, default=0),
        sa.Column("additional_minutes_purchased", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "period_year", "period_month", name="uq_user_period"),
    )
    op.create_index("ix_usage_records_user_id", "usage_records", ["user_id"])

    # Create payment_history table
    op.create_table(
        "payment_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.String(100), nullable=True),
        sa.Column("stripe_invoice_id", sa.String(100), nullable=True),
        sa.Column("payment_type", sa.String(30), nullable=False, default="subscription"),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, default="jpy"),
        sa.Column("minutes_purchased", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_payment_history_user_id", "payment_history", ["user_id"])
    op.create_index("ix_payment_history_stripe_payment_intent_id", "payment_history", ["stripe_payment_intent_id"])


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_index("ix_payment_history_stripe_payment_intent_id", table_name="payment_history")
    op.drop_index("ix_payment_history_user_id", table_name="payment_history")
    op.drop_table("payment_history")

    op.drop_index("ix_usage_records_user_id", table_name="usage_records")
    op.drop_table("usage_records")

    op.drop_index("ix_generated_videos_status", table_name="generated_videos")
    op.drop_index("ix_generated_videos_user_id", table_name="generated_videos")
    op.drop_table("generated_videos")

    op.drop_index("ix_voice_models_status", table_name="voice_models")
    op.drop_index("ix_voice_models_user_id", table_name="voice_models")
    op.drop_table("voice_models")

    op.drop_index("ix_video_models_status", table_name="video_models")
    op.drop_index("ix_video_models_user_id", table_name="video_models")
    op.drop_table("video_models")

    op.drop_index("ix_subscriptions_stripe_subscription_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_stripe_customer_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_table("user_settings")
    op.drop_table("user_profiles")

    op.drop_column("users", "avatar_url")
