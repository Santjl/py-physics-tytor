"""add attempt_feedbacks table

Revision ID: 0004_add_attempt_feedback
Revises: 0003_add_tsvector_fts
Branch Labels: None
Depends on: None
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_add_attempt_feedback"
down_revision = "0003_add_tsvector_fts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attempt_feedbacks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("attempt_id", sa.Integer, sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("data", sa.JSON, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_attempt_feedbacks_attempt_id", "attempt_feedbacks", ["attempt_id"])


def downgrade():
    op.drop_table("attempt_feedbacks")
