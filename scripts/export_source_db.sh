#!/usr/bin/env bash
# Export the source PostgreSQL (Supabase) data needed for the SQLite migration.
#
# Output: one JSON Lines file per table in OUT_DIR (default: the Git-ignored
# meigen-fly-private/source-db/data directory). Every file is written from a
# single REPEATABLE READ, READ ONLY transaction, so the dump is one consistent
# snapshot. Only the columns the new schema needs are exported; row UUID,
# ip_hash and user_agent of quote_likes never leave the source database.
#
# Usage:
#   export SUPABASE_DB_URL="$(security find-generic-password -s meigen-fly-supabase-db -w)"
#   scripts/export_source_db.sh [OUT_DIR]
set -euo pipefail

OUT_DIR="${1:-$HOME/prj/meigen-fly-private/source-db/data}"
: "${SUPABASE_DB_URL:?set SUPABASE_DB_URL before running (do not write it to a file)}"
mkdir -p "$OUT_DIR"

# Server-side session defaults: read-only and UTC for the whole session.
export PGOPTIONS="-c default_transaction_read_only=on -c TimeZone=UTC"

psql "$SUPABASE_DB_URL" -X -q -A -t -v ON_ERROR_STOP=1 <<SQL
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;

\o $OUT_DIR/export_meta.jsonl
SELECT row_to_json(t) FROM (
  SELECT now() AS exported_at, current_setting('TimeZone') AS time_zone
) t;

\o $OUT_DIR/authors.jsonl
SELECT row_to_json(t) FROM (
  SELECT id, name, slug, description, image_url, name_kana, name_foreign, name_reading,
         birth_date, birth_era, birth_precision, death_date, death_era, death_precision,
         created_at, updated_at
  FROM public.authors ORDER BY id
) t;

\o $OUT_DIR/professions.jsonl
SELECT row_to_json(t) FROM (
  SELECT id, name, slug, description, display_order, created_at, updated_at
  FROM public.professions ORDER BY id
) t;

\o $OUT_DIR/countries.jsonl
SELECT row_to_json(t) FROM (
  SELECT id, name, name_en, code, slug, created_at, updated_at
  FROM public.countries ORDER BY id
) t;

\o $OUT_DIR/source_types.jsonl
SELECT row_to_json(t) FROM (
  SELECT id, slug, name, display_order, description, created_at, updated_at
  FROM public.source_types ORDER BY id
) t;

\o $OUT_DIR/sources.jsonl
SELECT row_to_json(t) FROM (
  SELECT id, title, slug, author_id, published_year, description, created_at, updated_at
  FROM public.sources ORDER BY id
) t;

\o $OUT_DIR/characters.jsonl
SELECT row_to_json(t) FROM (
  SELECT id, name, slug, source_id, description, character_type, created_at, updated_at
  FROM public.characters ORDER BY id
) t;

\o $OUT_DIR/categories.jsonl
SELECT row_to_json(t) FROM (
  SELECT id, name, slug, description, sort_order, level, parent_id, color, created_at
  FROM public.categories ORDER BY id
) t;

\o $OUT_DIR/quotes.jsonl
SELECT row_to_json(t) FROM (
  SELECT id, text, text_en, author_id, source_id, character_id, weight, slug, enable,
         context_note, display_language_preference, created_at, updated_at
  FROM public.quotes ORDER BY id
) t;

\o $OUT_DIR/author_professions.jsonl
SELECT row_to_json(t) FROM (
  SELECT author_id, profession_id, display_order, created_at
  FROM public.author_professions ORDER BY author_id, profession_id
) t;

\o $OUT_DIR/author_country.jsonl
SELECT row_to_json(t) FROM (
  SELECT author_id, country_id, is_birth_country, created_at
  FROM public.author_country ORDER BY author_id, country_id
) t;

\o $OUT_DIR/source_type_assignments.jsonl
SELECT row_to_json(t) FROM (
  SELECT source_id, type_id, created_at
  FROM public.source_type_assignments ORDER BY source_id, type_id
) t;

\o $OUT_DIR/quote_categories.jsonl
SELECT row_to_json(t) FROM (
  SELECT quote_id, category_id
  FROM public.quote_categories ORDER BY quote_id, category_id
) t;

\o $OUT_DIR/quote_likes.jsonl
SELECT row_to_json(t) FROM (
  SELECT quote_id, client_uuid, created_at, is_valid
  FROM public.quote_likes ORDER BY quote_id, client_uuid
) t;

\o $OUT_DIR/legacy_votes.jsonl
SELECT row_to_json(t) FROM (
  SELECT quote_id, vote_count
  FROM public.legacy_votes ORDER BY quote_id
) t;

\o $OUT_DIR/quotes_sequence.jsonl
SELECT row_to_json(t) FROM (
  SELECT last_value, is_called FROM public.quotes_id_seq
) t;

\o
COMMIT;
SQL

for f in "$OUT_DIR"/*.jsonl; do
  printf '%8d  %s\n' "$(wc -l < "$f")" "$(basename "$f")"
done
