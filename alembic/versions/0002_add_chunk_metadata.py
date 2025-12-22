"""add chunk metadata columns

Revision ID: 0002_add_chunk_metadata
Revises: 0001_initial
Create Date: 2025-12-21 20:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_add_chunk_metadata"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    chunk_type = sa.Enum("theory", "exercise", "unknown", name="chunk_type")
    bind = op.get_bind()
    chunk_type.create(bind, checkfirst=True)

    op.add_column(
        "chunks",
        sa.Column("chunk_type", chunk_type, nullable=False, server_default="unknown"),
    )
    op.add_column("chunks", sa.Column("chapter_title", sa.Text(), nullable=True))
    op.add_column("chunks", sa.Column("section_title", sa.Text(), nullable=True))
    op.alter_column("chunks", "chunk_type", server_default=None)


def downgrade() -> None:
    op.drop_column("chunks", "section_title")
    op.drop_column("chunks", "chapter_title")
    op.drop_column("chunks", "chunk_type")
    chunk_type = sa.Enum("theory", "exercise", "unknown", name="chunk_type")
    bind = op.get_bind()
    chunk_type.drop(bind, checkfirst=True)
