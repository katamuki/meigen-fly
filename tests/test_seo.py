import io
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db import create_db_engine, get_connection, metadata
from app.instants import format_instant
from app.main import app
from app.schema import authors, categories, quotes, sources
from app.services import og_image
from app.services.og_image import (
    BG,
    BODY_BOTTOM,
    BODY_TOP,
    CONTENT_RIGHT,
    DEFAULT_OG_FILENAME,
    FOOT_BOTTOM,
    FOOT_GAP,
    FRAME_INSET,
    HEIGHT,
    NO_LINE_START,
    SEAL_SIZE,
    WIDTH,
    _brand_left,
    _font,
    _wrap,
    display_width,
    normalize_og_text,
    render_author_og,
    render_quote_og,
    size_step,
    truncate_to_width,
)
from app.services.redirects import resolve_legacy_redirect

ORIGIN = "http://localhost:8000"


@pytest.fixture
def seo_client(tmp_path: Path) -> Iterator[TestClient]:
    test_engine = create_db_engine(f"sqlite:///{tmp_path / 'seo.db'}")
    metadata.create_all(test_engine)
    created = format_instant(datetime(2026, 1, 1, tzinfo=UTC))
    updated = format_instant(datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC))

    with test_engine.begin() as connection:
        connection.execute(
            authors.insert(),
            {
                "id": 1,
                "name": "夏目漱石",
                "slug": "natsume-soseki",
                "description": "小説家。",
                "created_at": created,
                "updated_at": updated,
            },
        )
        connection.execute(
            sources.insert(),
            {
                "id": 20,
                "title": "こころ",
                "slug": "kokoro",
                "author_id": 1,
                "created_at": created,
                "updated_at": updated,
            },
        )
        connection.execute(
            categories.insert(),
            {
                "id": 30,
                "name": "人生",
                "slug": "life",
                "level": 1,
                "sort_order": 1,
                "created_at": created,
                "updated_at": updated,
            },
        )
        defaults = {
            "text_en": None,
            "context_note": None,
            "author_id": 1,
            "source_id": 20,
            "enable": 1,
            "display_language_preference": "ja",
            "legacy_vote_count": 0,
            "created_at": created,
            "updated_at": updated,
        }
        connection.execute(
            quotes.insert(),
            [
                defaults | {"id": 1, "slug": "with-slug", "text": "月が綺麗ですね"},
                defaults | {"id": 1002, "slug": None, "text": "スラッグのない名言"},
                defaults
                | {"id": 3, "slug": "hidden", "text": "非公開の名言", "enable": 0},
            ],
        )

    def override_connection() -> Iterator:
        with test_engine.begin() as connection:
            yield connection

    app.dependency_overrides[get_connection] = override_connection
    with TestClient(app, base_url=ORIGIN) as client:
        yield client
    app.dependency_overrides.clear()
    test_engine.dispose()


def head_of(body: str) -> str:
    return body.split("</head>", 1)[0]


def meta(body: str, pattern: str) -> str | None:
    match = re.search(pattern, head_of(body))
    return match.group(1) if match else None


# --- sitemap and robots -----------------------------------------------------


def test_sitemap_lists_public_quotes_authors_sources_and_categories(
    seo_client: TestClient,
) -> None:
    response = seo_client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml; charset=utf-8"
    assert response.headers["cache-control"] == "public, s-maxage=3600, max-age=600"
    body = response.text
    assert f"<loc>{ORIGIN}/</loc>" in body
    # Quotes follow the ADR 008 slug/qid contract, with updated_at as lastmod.
    assert f"<loc>{ORIGIN}/quotes/with-slug</loc>" in body
    assert f"<loc>{ORIGIN}/quotes/q1002</loc>" in body
    assert "<lastmod>2026-03-04</lastmod>" in body
    assert f"<loc>{ORIGIN}/authors/natsume-soseki</loc>" in body
    assert f"<loc>{ORIGIN}/sources/kokoro</loc>" in body
    assert f"<loc>{ORIGIN}/categories/life</loc>" in body
    # Disabled quotes and the noindex search page stay out.
    assert "/quotes/hidden" not in body
    assert f"<loc>{ORIGIN}/search</loc>" not in body


def test_robots_disallows_admin_api_and_search(seo_client: TestClient) -> None:
    response = seo_client.get("/robots.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "public, s-maxage=86400, max-age=3600"
    body = response.text
    assert "Disallow: /admin" in body
    assert "Disallow: /api/" in body
    assert "Disallow: /search" in body
    assert f"Sitemap: {ORIGIN}/sitemap.xml" in body


# --- canonical, OGP and structured data -------------------------------------


def test_quote_detail_carries_canonical_ogp_and_structured_data(
    seo_client: TestClient,
) -> None:
    body = seo_client.get("/quotes/with-slug").text

    assert meta(body, r'<link rel="canonical" href="([^"]+)"') == (
        f"{ORIGIN}/quotes/with-slug"
    )
    assert meta(body, r'og:url" content="([^"]+)"') == f"{ORIGIN}/quotes/with-slug"
    assert meta(body, r'og:type" content="([^"]+)"') == "article"
    assert meta(body, r'og:image" content="([^"]+)"') == (
        f"{ORIGIN}/quotes/with-slug/og.png"
    )
    assert meta(body, r'og:title" content="([^"]+)"').endswith("名言集.com")
    assert 'name="twitter:card" content="summary_large_image"' in body

    payload = json.loads(
        re.search(
            r'<script type="application/ld\+json">(.*?)</script>', body, re.DOTALL
        ).group(1)
    )
    quotation, breadcrumb = payload
    assert quotation["@type"] == "Quotation"
    assert quotation["text"] == "月が綺麗ですね"
    assert quotation["inLanguage"] == "ja"
    assert quotation["author"]["url"] == f"{ORIGIN}/authors/natsume-soseki"
    assert quotation["isPartOf"]["url"] == f"{ORIGIN}/sources/kokoro"
    assert breadcrumb["@type"] == "BreadcrumbList"
    assert breadcrumb["itemListElement"][-1]["item"] == f"{ORIGIN}/quotes/with-slug"


def test_author_detail_carries_person_structured_data_and_its_og_image(
    seo_client: TestClient,
) -> None:
    body = seo_client.get("/authors/natsume-soseki").text

    assert meta(body, r'og:image" content="([^"]+)"') == (
        f"{ORIGIN}/authors/natsume-soseki/og.png"
    )
    payload = json.loads(
        re.search(
            r'<script type="application/ld\+json">(.*?)</script>', body, re.DOTALL
        ).group(1)
    )
    assert payload[0]["@type"] == "Person"
    assert payload[0]["name"] == "夏目漱石"
    assert payload[1]["@type"] == "BreadcrumbList"


def test_pages_without_their_own_card_use_the_shared_og_image(
    seo_client: TestClient,
) -> None:
    body = seo_client.get("/quotes").text

    assert meta(body, r'og:image" content="([^"]+)"') == (
        f"{ORIGIN}/static/{DEFAULT_OG_FILENAME}"
    )
    assert meta(body, r'og:type" content="([^"]+)"') == "website"
    assert "application/ld+json" not in body


def test_canonical_keeps_the_page_and_filters_of_the_current_url(
    seo_client: TestClient,
) -> None:
    canonical = r'<link rel="canonical" href="([^"]+)"'

    assert meta(seo_client.get("/quotes?author_id=1").text, canonical) == (
        f"{ORIGIN}/quotes?author_id=1"
    )
    assert (
        meta(seo_client.get("/authors?page=1").text, canonical) == f"{ORIGIN}/authors"
    )
    # Both ranking entry points share one canonical URL.
    assert meta(seo_client.get("/ranking").text, canonical) == f"{ORIGIN}/ranking"
    assert (
        meta(seo_client.get("/ranking/quotes").text, canonical) == f"{ORIGIN}/ranking"
    )
    assert meta(seo_client.get("/ranking/authors").text, canonical) == (
        f"{ORIGIN}/ranking/authors"
    )


def test_search_page_stays_noindex_with_a_canonical(seo_client: TestClient) -> None:
    body = seo_client.get("/search?q=月").text

    assert '<meta name="robots" content="noindex">' in head_of(body)
    assert meta(body, r'<link rel="canonical" href="([^"]+)"') == f"{ORIGIN}/search"


# --- legacy redirects -------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/tools/old-page", "/"),
        ("/tools", "/"),
        ("/m/1", "/"),
        ("/countries/japan", "/"),
        ("/jobs/writer", "/professions"),
        ("/sources/view/12", "/sources"),
        ("/quotations/latest/3", "/quotes/latest"),
        ("/quotations/ranking/x", "/ranking"),
        ("/quotations/index/2", "/quotes"),
        ("/tags/view/1104/x", "/categories/friendship"),
        ("/tags/view/1115", "/categories/youth"),
        ("/tags/view/1111", "/categories/money"),
        ("/tags/view/1130", "/categories/hope"),
        ("/tags/view/9999", "/categories"),
        ("/authors/view/1976", "/authors/mushanokoji-saneatsu"),
        ("/authors/view/12", "/authors"),
        ("/quotes/page/1", "/quotes"),
        ("/quotes/latest/page/1", "/quotes/latest"),
        ("/categories/life/page/1", "/categories/life"),
        ("/authors/natsume-soseki/page/1", "/authors/natsume-soseki"),
        ("/characters/x/page/1", "/characters/x"),
    ],
)
def test_static_legacy_paths_redirect_once(path: str, target: str) -> None:
    assert resolve_legacy_redirect(path, "") == target


def test_prefix_rules_win_over_page_one_so_no_chain_is_built() -> None:
    assert resolve_legacy_redirect("/quotations/latest/page/1", "") == "/quotes/latest"


def test_page_one_keeps_filters_and_search_keeps_only_the_term() -> None:
    assert resolve_legacy_redirect("/quotes/page/1", "author_id=3") == (
        "/quotes?author_id=3"
    )
    assert resolve_legacy_redirect("/search/quotations", "q=%E6%9C%88&p=3") == (
        "/search?q=%E6%9C%88"
    )
    # Without a term the old site had no page there either.
    assert resolve_legacy_redirect("/search/quotations", "") is None


@pytest.mark.parametrize(
    ("path", "query", "target"),
    [
        ("/quotes/", "", "/quotes"),
        ("/quotes/", "author_id=1", "/quotes?author_id=1"),
        ("/authors/natsume-soseki/", "", "/authors/natsume-soseki"),
        # A legacy URL with a slash still takes one hop to its final target.
        ("/tools/", "", "/"),
        ("/quotes/page/1/", "", "/quotes"),
        ("/search/quotations/", "q=love", "/search?q=love"),
    ],
)
def test_trailing_slashes_are_removed_in_one_hop(
    path: str, query: str, target: str
) -> None:
    assert resolve_legacy_redirect(path, query) == target


@pytest.mark.parametrize(
    "path",
    [
        "//evil.example/page/1",
        "///evil.example/page/1",
        "/\\evil.example/page/1",
        "//evil.example/tools",
        "//evil.example/",
    ],
)
def test_protocol_relative_paths_never_become_a_redirect_target(path: str) -> None:
    # Otherwise stripping /page/1 hands back //evil.example, which a browser
    # resolves against another origin.
    assert resolve_legacy_redirect(path, "") is None


def test_untouched_paths_keep_routing() -> None:
    for path in (
        "/",
        "/quotes",
        "/quotes/page/2",
        "/authors/natsume-soseki",
        "/search",
    ):
        assert resolve_legacy_redirect(path, "") is None


def test_legacy_redirects_are_permanent_and_cacheable(seo_client: TestClient) -> None:
    response = seo_client.get("/tags/view/1104/x", follow_redirects=False)

    assert response.status_code == 301
    assert response.headers["location"] == "/categories/friendship"
    assert response.headers["cache-control"] == "public, s-maxage=86400, max-age=3600"


def test_trailing_slash_redirects_are_permanent_and_cacheable(
    seo_client: TestClient,
) -> None:
    # The old site's Next.js removed the slash with a 308 (ADR 008), so this is
    # a permanent redirect with a relative Location, not Starlette's 307.
    response = seo_client.get("/quotes/", follow_redirects=False)

    assert response.status_code == 301
    assert response.headers["location"] == "/quotes"
    assert response.headers["cache-control"] == "public, s-maxage=86400, max-age=3600"


def test_legacy_quote_ids_reach_the_final_canonical_in_one_hop(
    seo_client: TestClient,
) -> None:
    for path in ("/quotations/view/1.html", "/quotes/0001"):
        response = seo_client.get(path, follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/quotes/with-slug"

    without_slug = seo_client.get("/quotations/view/1002.html", follow_redirects=False)
    assert without_slug.status_code == 301
    assert without_slug.headers["location"] == "/quotes/q1002"


def test_legacy_quote_ids_without_a_public_quote_are_not_found(
    seo_client: TestClient,
) -> None:
    for path in (
        "/quotations/view/3.html",  # the quote exists but is not public
        "/quotations/view/9999.html",
        "/quotations/view/abc.html",
        "/quotes/9999",
    ):
        assert seo_client.get(path, follow_redirects=False).status_code == 404


# --- OG images --------------------------------------------------------------


def test_display_width_counts_wide_characters_as_one_and_latin_as_half() -> None:
    assert display_width("愛") == 1
    assert display_width("ab") == 1
    assert display_width("愛ab") == 2
    assert normalize_og_text("  改行\nと　空白  ") == "改行 と 空白"


@pytest.mark.parametrize(
    ("length", "step"),
    [(20, "short"), (21, "medium"), (40, "medium"), (41, "long"), (80, "long")],
)
def test_size_step_switches_at_twenty_and_forty(length: int, step: str) -> None:
    assert size_step("あ" * length) == step


def test_text_longer_than_eighty_is_truncated_with_an_ellipsis() -> None:
    truncated = truncate_to_width("あ" * 81)

    assert truncated.endswith("…")
    assert display_width(truncated) <= 80
    assert size_step(truncated) == "long"
    assert truncate_to_width("あ" * 80) == "あ" * 80
    # Latin counts as half width, so twice as many characters fit.
    assert truncate_to_width("a" * 160) == "a" * 160


def test_rendered_cards_are_1200x630_png() -> None:
    for png in (
        render_quote_og(text="月が綺麗ですね", language="ja", credit="夏目漱石"),
        render_quote_og(text="Live well.", language="en", credit="Anon"),
        render_author_og(name="夏目漱石"),
    ):
        image = Image.open(io.BytesIO(png))
        assert image.format == "PNG"
        assert image.size == (WIDTH, HEIGHT)


def test_a_long_credit_is_shortened_instead_of_running_under_the_brand() -> None:
    # A handful of real author names are wide enough to reach the brand lockup.
    png = render_quote_og(
        text="人生は素晴らしい。",
        language="ja",
        credit="フィリップ・スタンホープ (第4代チェスターフィールド伯爵)",
    )

    gap = Image.open(io.BytesIO(png)).crop(
        (
            int(_brand_left() - FOOT_GAP),
            FOOT_BOTTOM - SEAL_SIZE,
            int(_brand_left()),
            FOOT_BOTTOM,
        )
    )
    assert gap.getcolors() == [(gap.width * gap.height, BG)]


@pytest.mark.parametrize(
    "text",
    [
        "あ" * 9 + "。",
        "あ" * 9 + "ーーー",
        "大恋愛の経験のある者は友情を重んじない。",
        "僕は平和が怖い。何よりも怖い。……地獄を隠しているような気がしてね。",
    ],
)
def test_kinsoku_never_pushes_the_quote_past_the_right_edge(text: str) -> None:
    # Pulling closing marks back onto a full line used to run them off the card.
    png = render_quote_og(text=text, language="ja", credit="著者")

    margin = Image.open(io.BytesIO(png)).crop(
        (CONTENT_RIGHT + 1, BODY_TOP, WIDTH - FRAME_INSET - 1, BODY_BOTTOM)
    )
    assert margin.getcolors() == [(margin.width * margin.height, BG)]


def test_a_closing_mark_moves_down_with_the_character_before_it() -> None:
    text = "「" + "あ" * 9 + "。」"
    lines = _wrap(_font(96), text, [1000.0, 974.0])

    assert len(lines) > 1
    assert "".join(lines) == text
    assert all(line[0] not in NO_LINE_START for line in lines[1:])


def test_og_routes_serve_png_with_the_thirty_day_edge_cache(
    seo_client: TestClient,
) -> None:
    for path in ("/quotes/with-slug/og.png", "/authors/natsume-soseki/og.png"):
        response = seo_client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == (
            "public, s-maxage=2592000, max-age=86400"
        )
        assert Image.open(io.BytesIO(response.content)).size == (
            WIDTH,
            HEIGHT,
        )


def test_missing_or_private_targets_return_404_without_caching(
    seo_client: TestClient,
) -> None:
    for path in (
        "/quotes/hidden/og.png",
        "/quotes/q9999/og.png",
        "/authors/unknown/og.png",
    ):
        response = seo_client.get(path)
        assert response.status_code == 404
        assert response.headers["cache-control"] == "private, no-store"


def test_a_drawing_failure_falls_back_to_the_shared_card_uncached(
    seo_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(**_: object) -> bytes:
        raise RuntimeError("font missing")

    monkeypatch.setattr(og_image, "render_quote_og", broken)
    monkeypatch.setattr("app.routers.public.render_quote_og", broken)

    response = seo_client.get("/quotes/with-slug/og.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert Image.open(io.BytesIO(response.content)).size == (WIDTH, HEIGHT)
