"""add tsvector full-text search column to chunks

Revision ID: 0003_add_tsvector_fts
Revises: 0002_add_chunk_metadata
Create Date: 2026-02-10 00:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "0003_add_tsvector_fts"
down_revision = "0002_add_chunk_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_ts_config WHERE cfgname = 'portuguese_unaccent'
            ) THEN
                CREATE TEXT SEARCH CONFIGURATION portuguese_unaccent (COPY = portuguese);
                ALTER TEXT SEARCH CONFIGURATION portuguese_unaccent
                    ALTER MAPPING FOR hword, hword_part, word
                    WITH unaccent, portuguese_stem;
            END IF;
        END$$;
    """)

    op.execute("ALTER TABLE chunks ADD COLUMN text_search TSVECTOR")

    op.execute("""
        CREATE INDEX ix_chunks_text_search
        ON chunks USING GIN (text_search)
    """)

    op.execute("""
        UPDATE chunks
        SET text_search = to_tsvector('portuguese_unaccent', coalesce(text, ''))
        WHERE text_search IS NULL
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION chunks_text_search_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.text_search := to_tsvector('portuguese_unaccent', coalesce(NEW.text, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_chunks_text_search
        BEFORE INSERT OR UPDATE OF text ON chunks
        FOR EACH ROW EXECUTE FUNCTION chunks_text_search_trigger();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_chunks_text_search ON chunks")
    op.execute("DROP FUNCTION IF EXISTS chunks_text_search_trigger()")
    op.execute("DROP INDEX IF EXISTS ix_chunks_text_search")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS text_search")
