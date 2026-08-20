"""SQLAlchemy Core definitions of the 16 application tables.

The design source is docs/database/inventory-4-new-db-design.md (part 4) as
fixed by docs/database/migration-decisions.md. Constraint and index names follow
docs/database/migration-runbook.md §1. Integrity rules that span rows
(category hierarchy, level 2 assignment) are SQLite triggers defined in the
Alembic revision, not here.
"""

from sqlalchemy import (
    REAL,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)

from app.db import metadata

_HEX = "[0-9a-f]"
UUID_GLOB = "-".join(_HEX * n for n in (8, 4, 4, 4, 12))
DATE_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"


def _instant(name: str) -> Column:
    return Column(name, Text, nullable=False)


def _era_check(prefix: str) -> CheckConstraint:
    return CheckConstraint(f"{prefix}_era IN ('bc', 'ad')", name=f"{prefix}_era")


def _precision_check(prefix: str) -> CheckConstraint:
    return CheckConstraint(
        f"({prefix}_precision = 'unknown' AND {prefix}_date IS NULL)"
        f" OR ({prefix}_precision IN ('day', 'month', 'year')"
        f" AND {prefix}_date IS NOT NULL AND {prefix}_date GLOB '{DATE_GLOB}')",
        name=f"{prefix}_precision_date",
    )


authors = Table(
    "authors",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("description", Text),
    Column("image_url", Text),
    Column("name_kana", Text),
    Column("name_foreign", Text),
    Column("name_reading", Text),
    Column("birth_date", Text),
    Column("birth_era", Text, nullable=False, server_default="ad"),
    Column("birth_precision", Text, nullable=False, server_default="unknown"),
    Column("death_date", Text),
    Column("death_era", Text, nullable=False, server_default="ad"),
    Column("death_precision", Text, nullable=False, server_default="unknown"),
    _instant("created_at"),
    _instant("updated_at"),
    UniqueConstraint("slug"),
    _era_check("birth"),
    _era_check("death"),
    _precision_check("birth"),
    _precision_check("death"),
    # Reject an AD birth followed by a BC death when both dates are known.
    CheckConstraint(
        "NOT (birth_era = 'ad' AND death_era = 'bc'"
        " AND birth_date IS NOT NULL AND death_date IS NOT NULL)",
        name="era_order",
    ),
    # With day precision on both ends, reject an obvious reversal. BC years
    # count down, so only the year part is compared in reverse.
    CheckConstraint(
        "NOT (birth_precision = 'day' AND death_precision = 'day' AND ("
        "(birth_era = 'ad' AND death_era = 'ad' AND birth_date > death_date)"
        " OR (birth_era = 'bc' AND death_era = 'bc' AND ("
        "substr(birth_date, 1, 4) < substr(death_date, 1, 4)"
        " OR (substr(birth_date, 1, 4) = substr(death_date, 1, 4)"
        " AND substr(birth_date, 6) > substr(death_date, 6))))))",
        name="day_order",
    ),
    Index(None, "name_reading", "id"),
)

professions = Table(
    "professions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("description", Text),
    Column("display_order", Integer, nullable=False, server_default="0"),
    _instant("created_at"),
    _instant("updated_at"),
    UniqueConstraint("name"),
    UniqueConstraint("slug"),
    CheckConstraint("display_order >= 0", name="display_order"),
    Index(None, "display_order", "id"),
)

countries = Table(
    "countries",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_en", Text),
    Column("code", Text),
    Column("slug", Text, nullable=False),
    _instant("created_at"),
    _instant("updated_at"),
    UniqueConstraint("name"),
    UniqueConstraint("slug"),
    CheckConstraint(
        "code IS NULL OR code GLOB '[A-Za-z][A-Za-z]'"
        " OR code GLOB '[A-Za-z][A-Za-z][A-Za-z]'",
        name="code",
    ),
    Index(None, "code"),
)

source_types = Table(
    "source_types",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("slug", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("display_order", Integer, nullable=False, server_default="0"),
    Column("description", Text),
    _instant("created_at"),
    _instant("updated_at"),
    UniqueConstraint("slug"),
    CheckConstraint("display_order >= 0", name="display_order"),
    Index(None, "display_order", "id"),
)

sources = Table(
    "sources",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("author_id", Integer, ForeignKey("authors.id", ondelete="SET NULL")),
    Column("published_year", Integer),
    Column("description", Text),
    _instant("created_at"),
    _instant("updated_at"),
    UniqueConstraint("slug"),
    CheckConstraint(
        "published_year IS NULL OR published_year >= 1", name="published_year"
    ),
    Index(None, "author_id"),
)

characters = Table(
    "characters",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("source_id", Integer, ForeignKey("sources.id", ondelete="SET NULL")),
    Column("description", Text),
    Column("character_type", Text, nullable=False, server_default="character"),
    _instant("created_at"),
    _instant("updated_at"),
    UniqueConstraint("slug"),
    CheckConstraint(
        "character_type IN ('character', 'narrator', 'author_voice')",
        name="character_type",
    ),
    Index(None, "source_id"),
)

categories = Table(
    "categories",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("description", Text),
    Column("sort_order", Integer, nullable=False, server_default="0"),
    Column("level", Integer, nullable=False, server_default="1"),
    Column("parent_id", Integer, ForeignKey("categories.id", ondelete="RESTRICT")),
    Column("color", Text),
    _instant("created_at"),
    _instant("updated_at"),
    UniqueConstraint("slug"),
    CheckConstraint("sort_order >= 0", name="sort_order"),
    CheckConstraint(
        "(level = 1 AND parent_id IS NULL) OR (level = 2 AND parent_id IS NOT NULL)",
        name="level_parent",
    ),
    Index(None, "parent_id", "sort_order", "id"),
)

quotes = Table(
    "quotes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("text", Text, nullable=False),
    Column("text_en", Text),
    Column("author_id", Integer, ForeignKey("authors.id", ondelete="SET NULL")),
    Column("source_id", Integer, ForeignKey("sources.id", ondelete="SET NULL")),
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="SET NULL")),
    Column("weight", Integer, nullable=False, server_default="5"),
    Column("slug", Text),
    Column("enable", Integer, nullable=False, server_default="1"),
    Column("context_note", Text),
    Column("display_language_preference", Text, nullable=False, server_default="ja"),
    Column("legacy_vote_count", Integer, nullable=False, server_default="0"),
    _instant("created_at"),
    _instant("updated_at"),
    UniqueConstraint("slug"),
    CheckConstraint("weight BETWEEN 1 AND 10", name="weight"),
    CheckConstraint("enable IN (0, 1)", name="enable"),
    CheckConstraint(
        "display_language_preference IN ('ja', 'en')",
        name="display_language_preference",
    ),
    CheckConstraint("legacy_vote_count >= 0", name="legacy_vote_count"),
    CheckConstraint("text <> '' OR coalesce(text_en, '') <> ''", name="text_present"),
    Index(None, "enable", "id"),
    Index(None, "author_id", "enable", "id"),
    Index(None, "source_id", "enable", "id"),
    Index(None, "character_id", "enable", "id"),
    sqlite_autoincrement=True,
)

author_professions = Table(
    "author_professions",
    metadata,
    Column(
        "author_id",
        Integer,
        ForeignKey("authors.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "profession_id",
        Integer,
        ForeignKey("professions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("display_order", Integer, nullable=False),
    _instant("created_at"),
    PrimaryKeyConstraint("author_id", "profession_id"),
    UniqueConstraint("author_id", "display_order"),
    CheckConstraint("display_order >= 1", name="display_order"),
    Index(None, "profession_id", "author_id"),
)

author_country = Table(
    "author_country",
    metadata,
    Column(
        "author_id",
        Integer,
        ForeignKey("authors.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "country_id",
        Integer,
        ForeignKey("countries.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("is_birth_country", Integer, nullable=False, server_default="0"),
    _instant("created_at"),
    PrimaryKeyConstraint("author_id", "country_id"),
    CheckConstraint("is_birth_country IN (0, 1)", name="is_birth_country"),
    Index(None, "country_id", "author_id"),
    # At most one birth country per author.
    Index(
        "uq_author_country_birth_country",
        "author_id",
        unique=True,
        sqlite_where=text("is_birth_country = 1"),
    ),
)

source_type_assignments = Table(
    "source_type_assignments",
    metadata,
    Column(
        "source_id",
        Integer,
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "type_id",
        Integer,
        ForeignKey("source_types.id", ondelete="CASCADE"),
        nullable=False,
    ),
    _instant("created_at"),
    PrimaryKeyConstraint("source_id", "type_id"),
    Index(None, "type_id", "source_id"),
)

quote_categories = Table(
    "quote_categories",
    metadata,
    Column(
        "quote_id", Integer, ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    ),
    Column(
        "category_id",
        Integer,
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
    ),
    PrimaryKeyConstraint("quote_id", "category_id"),
    Index(None, "category_id", "quote_id"),
)

quote_likes = Table(
    "quote_likes",
    metadata,
    Column(
        "quote_id", Integer, ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    ),
    Column("client_uuid", Text, nullable=False),
    _instant("created_at"),
    Column("is_valid", Integer, nullable=False, server_default="1"),
    PrimaryKeyConstraint("quote_id", "client_uuid"),
    CheckConstraint(f"client_uuid GLOB '{UUID_GLOB}'", name="client_uuid"),
    CheckConstraint("is_valid IN (0, 1)", name="is_valid"),
    Index(None, "is_valid", "created_at", "quote_id"),
)

quote_ranking_scores = Table(
    "quote_ranking_scores",
    metadata,
    Column(
        "quote_id",
        Integer,
        ForeignKey("quotes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("score_total", REAL, nullable=False),
    Column("likes_total", Integer, nullable=False),
    Column("likes_7d", Integer, nullable=False),
    Column("likes_1d", Integer, nullable=False),
    _instant("refreshed_at"),
    CheckConstraint(
        "likes_1d >= 0 AND likes_1d <= likes_7d AND likes_7d <= likes_total",
        name="likes",
    ),
)
Index(
    "ix_quote_ranking_scores_score_total_quote_id",
    quote_ranking_scores.c.score_total.desc(),
    quote_ranking_scores.c.quote_id,
)

author_rankings = Table(
    "author_rankings",
    metadata,
    Column(
        "author_id",
        Integer,
        ForeignKey("authors.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("rank", Integer, nullable=False),
    Column("score", REAL, nullable=False),
    Column("total_score", REAL, nullable=False),
    Column("avg_score", REAL, nullable=False),
    Column("quote_count", Integer, nullable=False),
    _instant("refreshed_at"),
    CheckConstraint("rank >= 1", name="rank"),
    CheckConstraint("quote_count >= 0", name="quote_count"),
    Index(None, "rank", "author_id"),
)

category_rankings = Table(
    "category_rankings",
    metadata,
    Column(
        "category_id",
        Integer,
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("rank", Integer, nullable=False),
    Column("score", REAL, nullable=False),
    Column("total_score", REAL, nullable=False),
    Column("avg_score", REAL, nullable=False),
    Column("adjusted_score", REAL, nullable=False),
    Column("quote_count", Integer, nullable=False),
    _instant("refreshed_at"),
    CheckConstraint("rank >= 1", name="rank"),
    CheckConstraint("quote_count >= 0", name="quote_count"),
    Index(None, "rank", "category_id"),
)
