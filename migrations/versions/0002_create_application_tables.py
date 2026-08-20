"""Create the 16 application tables.

Revision ID: 0002
Revises: 0001

Design: docs/database/inventory-4-new-db-design.md as fixed by
docs/database/migration-decisions.md; naming rules and trigger list in
docs/database/migration-runbook.md. The create_table calls were drafted with
autogenerate from app/schema.py and reviewed by hand; the triggers are
hand-written because they cannot be expressed in SQLAlchemy metadata.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "authors",
    "categories",
    "countries",
    "professions",
    "source_types",
    "author_country",
    "author_professions",
    "author_rankings",
    "category_rankings",
    "sources",
    "characters",
    "source_type_assignments",
    "quotes",
    "quote_categories",
    "quote_likes",
    "quote_ranking_scores",
)

# Cross-row integrity rules (design §4.7, §5.4). Plain CHECK constraints cannot
# reference other rows or tables, so these are SQLite triggers.
TRIGGER_SQL = {
    # A level 2 category must point at an existing level 1 category.
    "trg_categories_insert_parent_level": """
        CREATE TRIGGER trg_categories_insert_parent_level
        BEFORE INSERT ON categories
        WHEN NEW.level = 2 AND NOT EXISTS (
            SELECT 1 FROM categories p WHERE p.id = NEW.parent_id AND p.level = 1
        )
        BEGIN
            SELECT RAISE(ABORT, 'categories: parent of a level 2 category must be level 1');
        END
    """,
    "trg_categories_update_parent_level": """
        CREATE TRIGGER trg_categories_update_parent_level
        BEFORE UPDATE OF level, parent_id ON categories
        WHEN NEW.level = 2 AND (
            NEW.parent_id = NEW.id OR NOT EXISTS (
                SELECT 1 FROM categories p WHERE p.id = NEW.parent_id AND p.level = 1
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'categories: parent of a level 2 category must be level 1');
        END
    """,
    # A category's level is fixed while children or quote assignments rely on it.
    "trg_categories_update_level_in_use": """
        CREATE TRIGGER trg_categories_update_level_in_use
        BEFORE UPDATE OF level ON categories
        WHEN NEW.level <> OLD.level AND (
            EXISTS (SELECT 1 FROM categories c WHERE c.parent_id = OLD.id)
            OR EXISTS (SELECT 1 FROM quote_categories qc WHERE qc.category_id = OLD.id)
        )
        BEGIN
            SELECT RAISE(ABORT, 'categories: level cannot change while children or quote assignments exist');
        END
    """,
    # Quotes are assigned to level 2 categories only.
    "trg_quote_categories_insert_level2": """
        CREATE TRIGGER trg_quote_categories_insert_level2
        BEFORE INSERT ON quote_categories
        WHEN NOT EXISTS (
            SELECT 1 FROM categories c WHERE c.id = NEW.category_id AND c.level = 2
        )
        BEGIN
            SELECT RAISE(ABORT, 'quote_categories: category must be level 2');
        END
    """,
    "trg_quote_categories_update_level2": """
        CREATE TRIGGER trg_quote_categories_update_level2
        BEFORE UPDATE OF category_id ON quote_categories
        WHEN NOT EXISTS (
            SELECT 1 FROM categories c WHERE c.id = NEW.category_id AND c.level = 2
        )
        BEGIN
            SELECT RAISE(ABORT, 'quote_categories: category must be level 2');
        END
    """,
}
TRIGGERS = tuple(TRIGGER_SQL)


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("name_kana", sa.Text(), nullable=True),
        sa.Column("name_foreign", sa.Text(), nullable=True),
        sa.Column("name_reading", sa.Text(), nullable=True),
        sa.Column("birth_date", sa.Text(), nullable=True),
        sa.Column("birth_era", sa.Text(), server_default="ad", nullable=False),
        sa.Column(
            "birth_precision", sa.Text(), server_default="unknown", nullable=False
        ),
        sa.Column("death_date", sa.Text(), nullable=True),
        sa.Column("death_era", sa.Text(), server_default="ad", nullable=False),
        sa.Column(
            "death_precision", sa.Text(), server_default="unknown", nullable=False
        ),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(birth_precision = 'unknown' AND birth_date IS NULL) OR (birth_precision IN ('day', 'month', 'year') AND birth_date IS NOT NULL AND birth_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')",
            name=op.f("ck_authors_birth_precision_date"),
        ),
        sa.CheckConstraint(
            "(death_precision = 'unknown' AND death_date IS NULL) OR (death_precision IN ('day', 'month', 'year') AND death_date IS NOT NULL AND death_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')",
            name=op.f("ck_authors_death_precision_date"),
        ),
        sa.CheckConstraint(
            "NOT (birth_era = 'ad' AND death_era = 'bc' AND birth_date IS NOT NULL AND death_date IS NOT NULL)",
            name=op.f("ck_authors_era_order"),
        ),
        sa.CheckConstraint(
            "NOT (birth_precision = 'day' AND death_precision = 'day' AND ((birth_era = 'ad' AND death_era = 'ad' AND birth_date > death_date) OR (birth_era = 'bc' AND death_era = 'bc' AND (substr(birth_date, 1, 4) < substr(death_date, 1, 4) OR (substr(birth_date, 1, 4) = substr(death_date, 1, 4) AND substr(birth_date, 6) > substr(death_date, 6))))))",
            name=op.f("ck_authors_day_order"),
        ),
        sa.CheckConstraint(
            "birth_era IN ('bc', 'ad')", name=op.f("ck_authors_birth_era")
        ),
        sa.CheckConstraint(
            "death_era IN ('bc', 'ad')", name=op.f("ck_authors_death_era")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_authors")),
        sa.UniqueConstraint("slug", name=op.f("uq_authors_slug")),
    )
    op.create_index(
        op.f("ix_authors_name_reading_id"),
        "authors",
        ["name_reading", "id"],
        unique=False,
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("level", sa.Integer(), server_default="1", nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(level = 1 AND parent_id IS NULL) OR (level = 2 AND parent_id IS NOT NULL)",
            name=op.f("ck_categories_level_parent"),
        ),
        sa.CheckConstraint("sort_order >= 0", name=op.f("ck_categories_sort_order")),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name=op.f("fk_categories_parent_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("slug", name=op.f("uq_categories_slug")),
    )
    op.create_index(
        op.f("ix_categories_parent_id_sort_order_id"),
        "categories",
        ["parent_id", "sort_order", "id"],
        unique=False,
    )

    op.create_table(
        "countries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "code IS NULL OR code GLOB '[A-Za-z][A-Za-z]' OR code GLOB '[A-Za-z][A-Za-z][A-Za-z]'",
            name=op.f("ck_countries_code"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_countries")),
        sa.UniqueConstraint("name", name=op.f("uq_countries_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_countries_slug")),
    )
    op.create_index(op.f("ix_countries_code"), "countries", ["code"], unique=False)

    op.create_table(
        "professions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "display_order >= 0", name=op.f("ck_professions_display_order")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_professions")),
        sa.UniqueConstraint("name", name=op.f("uq_professions_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_professions_slug")),
    )
    op.create_index(
        op.f("ix_professions_display_order_id"),
        "professions",
        ["display_order", "id"],
        unique=False,
    )

    op.create_table(
        "source_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "display_order >= 0", name=op.f("ck_source_types_display_order")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_types")),
        sa.UniqueConstraint("slug", name=op.f("uq_source_types_slug")),
    )
    op.create_index(
        op.f("ix_source_types_display_order_id"),
        "source_types",
        ["display_order", "id"],
        unique=False,
    )

    op.create_table(
        "author_country",
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("country_id", sa.Integer(), nullable=False),
        sa.Column("is_birth_country", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "is_birth_country IN (0, 1)",
            name=op.f("ck_author_country_is_birth_country"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["authors.id"],
            name=op.f("fk_author_country_author_id_authors"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["country_id"],
            ["countries.id"],
            name=op.f("fk_author_country_country_id_countries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "author_id", "country_id", name=op.f("pk_author_country")
        ),
    )
    op.create_index(
        op.f("ix_author_country_country_id_author_id"),
        "author_country",
        ["country_id", "author_id"],
        unique=False,
    )
    op.create_index(
        "uq_author_country_birth_country",
        "author_country",
        ["author_id"],
        unique=True,
        sqlite_where=sa.text("is_birth_country = 1"),
    )

    op.create_table(
        "author_professions",
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("profession_id", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "display_order >= 1", name=op.f("ck_author_professions_display_order")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["authors.id"],
            name=op.f("fk_author_professions_author_id_authors"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profession_id"],
            ["professions.id"],
            name=op.f("fk_author_professions_profession_id_professions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "author_id", "profession_id", name=op.f("pk_author_professions")
        ),
        sa.UniqueConstraint(
            "author_id",
            "display_order",
            name=op.f("uq_author_professions_author_id_display_order"),
        ),
    )
    op.create_index(
        op.f("ix_author_professions_profession_id_author_id"),
        "author_professions",
        ["profession_id", "author_id"],
        unique=False,
    )

    op.create_table(
        "author_rankings",
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.REAL(), nullable=False),
        sa.Column("total_score", sa.REAL(), nullable=False),
        sa.Column("avg_score", sa.REAL(), nullable=False),
        sa.Column("quote_count", sa.Integer(), nullable=False),
        sa.Column("refreshed_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "quote_count >= 0", name=op.f("ck_author_rankings_quote_count")
        ),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_author_rankings_rank")),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["authors.id"],
            name=op.f("fk_author_rankings_author_id_authors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("author_id", name=op.f("pk_author_rankings")),
    )
    op.create_index(
        op.f("ix_author_rankings_rank_author_id"),
        "author_rankings",
        ["rank", "author_id"],
        unique=False,
    )

    op.create_table(
        "category_rankings",
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.REAL(), nullable=False),
        sa.Column("total_score", sa.REAL(), nullable=False),
        sa.Column("avg_score", sa.REAL(), nullable=False),
        sa.Column("adjusted_score", sa.REAL(), nullable=False),
        sa.Column("quote_count", sa.Integer(), nullable=False),
        sa.Column("refreshed_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "quote_count >= 0", name=op.f("ck_category_rankings_quote_count")
        ),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_category_rankings_rank")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_category_rankings_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("category_id", name=op.f("pk_category_rankings")),
    )
    op.create_index(
        op.f("ix_category_rankings_rank_category_id"),
        "category_rankings",
        ["rank", "category_id"],
        unique=False,
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("published_year", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "published_year IS NULL OR published_year >= 1",
            name=op.f("ck_sources_published_year"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["authors.id"],
            name=op.f("fk_sources_author_id_authors"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("slug", name=op.f("uq_sources_slug")),
    )
    op.create_index(
        op.f("ix_sources_author_id"), "sources", ["author_id"], unique=False
    )

    op.create_table(
        "characters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "character_type", sa.Text(), server_default="character", nullable=False
        ),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "character_type IN ('character', 'narrator', 'author_voice')",
            name=op.f("ck_characters_character_type"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_characters_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_characters")),
        sa.UniqueConstraint("slug", name=op.f("uq_characters_slug")),
    )
    op.create_index(
        op.f("ix_characters_source_id"), "characters", ["source_id"], unique=False
    )

    op.create_table(
        "source_type_assignments",
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("type_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_source_type_assignments_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["type_id"],
            ["source_types.id"],
            name=op.f("fk_source_type_assignments_type_id_source_types"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "source_id", "type_id", name=op.f("pk_source_type_assignments")
        ),
    )
    op.create_index(
        op.f("ix_source_type_assignments_type_id_source_id"),
        "source_type_assignments",
        ["type_id", "source_id"],
        unique=False,
    )

    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_en", sa.Text(), nullable=True),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("character_id", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Integer(), server_default="5", nullable=False),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("enable", sa.Integer(), server_default="1", nullable=False),
        sa.Column("context_note", sa.Text(), nullable=True),
        sa.Column(
            "display_language_preference",
            sa.Text(),
            server_default="ja",
            nullable=False,
        ),
        sa.Column(
            "legacy_vote_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "display_language_preference IN ('ja', 'en')",
            name=op.f("ck_quotes_display_language_preference"),
        ),
        sa.CheckConstraint(
            "text <> '' OR coalesce(text_en, '') <> ''",
            name=op.f("ck_quotes_text_present"),
        ),
        sa.CheckConstraint("enable IN (0, 1)", name=op.f("ck_quotes_enable")),
        sa.CheckConstraint(
            "legacy_vote_count >= 0", name=op.f("ck_quotes_legacy_vote_count")
        ),
        sa.CheckConstraint("weight BETWEEN 1 AND 10", name=op.f("ck_quotes_weight")),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["authors.id"],
            name=op.f("fk_quotes_author_id_authors"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            name=op.f("fk_quotes_character_id_characters"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_quotes_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quotes")),
        sa.UniqueConstraint("slug", name=op.f("uq_quotes_slug")),
        sqlite_autoincrement=True,
    )
    op.create_index(
        op.f("ix_quotes_author_id_enable_id"),
        "quotes",
        ["author_id", "enable", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quotes_character_id_enable_id"),
        "quotes",
        ["character_id", "enable", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quotes_enable_id"), "quotes", ["enable", "id"], unique=False
    )
    op.create_index(
        op.f("ix_quotes_source_id_enable_id"),
        "quotes",
        ["source_id", "enable", "id"],
        unique=False,
    )

    op.create_table(
        "quote_categories",
        sa.Column("quote_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_quote_categories_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name=op.f("fk_quote_categories_quote_id_quotes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "quote_id", "category_id", name=op.f("pk_quote_categories")
        ),
    )
    op.create_index(
        op.f("ix_quote_categories_category_id_quote_id"),
        "quote_categories",
        ["category_id", "quote_id"],
        unique=False,
    )

    op.create_table(
        "quote_likes",
        sa.Column("quote_id", sa.Integer(), nullable=False),
        sa.Column("client_uuid", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("is_valid", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "client_uuid GLOB '[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'",
            name=op.f("ck_quote_likes_client_uuid"),
        ),
        sa.CheckConstraint("is_valid IN (0, 1)", name=op.f("ck_quote_likes_is_valid")),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name=op.f("fk_quote_likes_quote_id_quotes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("quote_id", "client_uuid", name=op.f("pk_quote_likes")),
    )
    op.create_index(
        op.f("ix_quote_likes_is_valid_created_at_quote_id"),
        "quote_likes",
        ["is_valid", "created_at", "quote_id"],
        unique=False,
    )

    op.create_table(
        "quote_ranking_scores",
        sa.Column("quote_id", sa.Integer(), nullable=False),
        sa.Column("score_total", sa.REAL(), nullable=False),
        sa.Column("likes_total", sa.Integer(), nullable=False),
        sa.Column("likes_7d", sa.Integer(), nullable=False),
        sa.Column("likes_1d", sa.Integer(), nullable=False),
        sa.Column("refreshed_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "likes_1d >= 0 AND likes_1d <= likes_7d AND likes_7d <= likes_total",
            name=op.f("ck_quote_ranking_scores_likes"),
        ),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name=op.f("fk_quote_ranking_scores_quote_id_quotes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("quote_id", name=op.f("pk_quote_ranking_scores")),
    )
    op.create_index(
        "ix_quote_ranking_scores_score_total_quote_id",
        "quote_ranking_scores",
        [sa.literal_column("score_total DESC"), "quote_id"],
        unique=False,
    )

    for sql in TRIGGER_SQL.values():
        op.execute(sql)


def downgrade() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for table in reversed(TABLES):
        if table == "categories":
            # Self-referencing RESTRICT FK: remove children before the implicit
            # DELETE that DROP TABLE performs with foreign keys enabled.
            op.execute("DELETE FROM categories WHERE level = 2")
        op.drop_table(table)
