"""Pillow rendering of the 1200x630 OG images (ADR 018).

The visual spec is docs/design/proposal-b/og/og.html: a Light-only "washi x ink
x indigo" card with a hairline rule, the quote, the credit and a seal-style
brand. That HTML is never rendered in production; the constants below are the
transcription of it. Translucent CSS colors are pre-composited over the washi
background because the canvas is opaque, and CSS letter-spacing has no Pillow
equivalent, so it is dropped.
"""

import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from unicodedata import east_asian_width

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1200
HEIGHT = 630

BG = (247, 243, 234)
INK = (26, 23, 20)
SUBTLE = (154, 143, 128)
ACCENT = (44, 90, 140)
FRAME_LINE = (220, 217, 208)  # rgba(26,23,20,.12) over the washi background
HAIRLINE = (64, 105, 149)  # the indigo accent at 90% over the same background

FRAME_INSET = 40
FRAME_RADIUS = 6
HAIRLINE_X = 96
HAIRLINE_TOP = 110
HAIRLINE_BOTTOM = 480

CONTENT_LEFT = 130  # 96px page padding + 34px clearance from the hairline
CONTENT_RIGHT = 1104
BODY_TOP = 84
BODY_BOTTOM = 482
FOOT_BOTTOM = 546

CREDIT_SIZE = 36
CREDIT_PREFIX = "— "
SEAL_SIZE = 64
SEAL_RADIUS = 10
SEAL_TEXT = "名"
SEAL_TEXT_SIZE = 34
BRAND_GAP = 18
BRAND_NAME = "名言集"
BRAND_SUFFIX = ".com"
BRAND_SIZE = 30

# Built by scripts/build_default_og.py and served as the fallback OG image.
DEFAULT_OG_FILENAME = "og-default.c5f86223.png"

AUTHOR_SUBTITLE = "名言・格言"
DEFAULT_OG_TEXT = "心に響く名言・格言"
UNKNOWN_CREDIT = "作者不明"

# ADR 018: display width 20 / 40 / 80 select the three steps, and anything
# longer is truncated to 80 including the ellipsis and drawn as "long".
SHORT_WIDTH = 20
MEDIUM_WIDTH = 40
MAX_WIDTH = 80
ELLIPSIS = "…"

# (font size, line height) per step, matching og.html's two type scales.
QUOTE_TYPE = {
    ("ja", "short"): (96, 1.40),
    ("ja", "medium"): (66, 1.55),
    ("ja", "long"): (46, 1.72),
    ("en", "short"): (104, 1.25),
    ("en", "medium"): (72, 1.35),
    ("en", "long"): (50, 1.50),
}

# Debian's fonts-noto-cjk first (ADR 018's production font), then the mincho
# faces that ship with macOS so local development renders the same layout.
FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-SemiBold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifJP-SemiBold.otf",
    "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
)
_MAX_FACES = 16
_HEAVY_STYLES = frozenset({"W6", "SemiBold", "Semibold", "DemiBold", "Bold"})

# Characters that may not open a line. The previous line takes them back, which
# is the minimal kinsoku ADR 018 asks for.
NO_LINE_START = frozenset(
    "」』）］｝〉》〕】、。，．・：；？！ーゝゞ々"
    "ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ"
    ",.:;?!)]}%…’”"
)

# One Latin word stays on one line; everything else can break per character.
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-]*|\s+|.", re.DOTALL)


class OgFontUnavailableError(RuntimeError):
    """Raised when no Japanese serif font is installed on this machine."""


def _face_index(path: str) -> int | None:
    """Pick the Japanese face, preferring the semibold weight og.html uses."""
    best: tuple[tuple[bool, bool], int] | None = None
    for index in range(_MAX_FACES):
        try:
            family, style = ImageFont.truetype(path, 20, index=index).getname()
        except OSError:
            break
        score = (
            "JP" in family or "ProN" in family or "Japanese" in family,
            style in _HEAVY_STYLES,
        )
        if best is None or score > best[0]:
            best = (score, index)
    return None if best is None else best[1]


@lru_cache(maxsize=1)
def _font_file() -> tuple[str, int]:
    for path in FONT_CANDIDATES:
        if not Path(path).exists():
            continue
        index = _face_index(path)
        if index is not None:
            return path, index
    raise OgFontUnavailableError("no Japanese serif font found for OG rendering")


@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont:
    path, index = _font_file()
    return ImageFont.truetype(path, size, index=index)


def normalize_og_text(value: str) -> str:
    """Collapse every run of whitespace, including newlines, into one space."""
    return " ".join(value.split())


def display_width(value: str) -> float:
    """Count East Asian wide, full and ambiguous characters as one, rest half."""
    return sum(1.0 if east_asian_width(ch) in "WFA" else 0.5 for ch in value)


def truncate_to_width(value: str, limit: float = MAX_WIDTH) -> str:
    """Shorten to ``limit`` display units, counting the appended ellipsis."""
    if display_width(value) <= limit:
        return value
    budget = limit - display_width(ELLIPSIS)
    kept: list[str] = []
    used = 0.0
    for char in value:
        char_width = display_width(char)
        if used + char_width > budget:
            break
        kept.append(char)
        used += char_width
    return "".join(kept).rstrip() + ELLIPSIS


def size_step(value: str) -> str:
    """Return the og--short / og--medium / og--long step for this text."""
    width = display_width(value)
    if width <= SHORT_WIDTH:
        return "short"
    if width <= MEDIUM_WIDTH:
        return "medium"
    return "long"


def _wrap(font: ImageFont.FreeTypeFont, text: str, limits: list[float]) -> list[str]:
    """Greedily wrap on measured glyph widths, then apply line-start kinsoku."""
    units: list[str] = []
    widest = max(limits)
    for token in _TOKEN_PATTERN.findall(text):
        if not token.isspace() and font.getlength(token) > widest:
            units.extend(token)  # A word wider than the canvas breaks per glyph.
        else:
            units.append(token)

    lines: list[str] = []
    current = ""
    for unit in units:
        limit = limits[min(len(lines), len(limits) - 1)]
        candidate = f"{current} " if unit.isspace() else current + unit
        if current and font.getlength(candidate.rstrip()) > limit:
            lines.append(current.rstrip())
            current = "" if unit.isspace() else unit
        else:
            current = candidate
    if current.strip():
        lines.append(current.rstrip())

    for index in range(1, len(lines)):
        while len(lines[index]) > 0 and lines[index][0] in NO_LINE_START:
            lines[index - 1] += lines[index][0]
            lines[index] = lines[index][1:]
    return [line for line in lines if line]


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (FRAME_INSET, FRAME_INSET, WIDTH - FRAME_INSET - 1, HEIGHT - FRAME_INSET - 1),
        radius=FRAME_RADIUS,
        outline=FRAME_LINE,
        width=1,
    )
    draw.rectangle(
        (HAIRLINE_X, HAIRLINE_TOP, HAIRLINE_X + 1, HAIRLINE_BOTTOM), fill=HAIRLINE
    )
    return image, draw


def _draw_brand(draw: ImageDraw.ImageDraw) -> None:
    """Draw the seal-style brand lockup, right aligned in the footer row."""
    brand_font = _font(BRAND_SIZE)
    seal_font = _font(SEAL_TEXT_SIZE)
    name_width = brand_font.getlength(BRAND_NAME)
    suffix_width = brand_font.getlength(BRAND_SUFFIX)
    name_left = CONTENT_RIGHT - name_width - suffix_width
    seal_right = name_left - BRAND_GAP
    seal_left = seal_right - SEAL_SIZE
    seal_top = FOOT_BOTTOM - SEAL_SIZE

    draw.rounded_rectangle(
        (seal_left, seal_top, seal_right, FOOT_BOTTOM),
        radius=SEAL_RADIUS,
        fill=ACCENT,
    )
    draw.text(
        (seal_left + SEAL_SIZE / 2, seal_top + SEAL_SIZE / 2),
        SEAL_TEXT,
        font=seal_font,
        fill=BG,
        anchor="mm",
    )
    middle = seal_top + SEAL_SIZE / 2
    draw.text((name_left, middle), BRAND_NAME, font=brand_font, fill=INK, anchor="lm")
    draw.text(
        (name_left + name_width, middle),
        BRAND_SUFFIX,
        font=brand_font,
        fill=ACCENT,
        anchor="lm",
    )


def _draw_credit(draw: ImageDraw.ImageDraw, credit: str, *, prefix: bool) -> None:
    """Draw the footer's left text, bottom aligned with the brand lockup."""
    font = _font(CREDIT_SIZE)
    x = CONTENT_LEFT
    if prefix:
        draw.text((x, FOOT_BOTTOM), CREDIT_PREFIX, font=font, fill=SUBTLE, anchor="ls")
        x += font.getlength(CREDIT_PREFIX)
    draw.text((x, FOOT_BOTTOM), credit, font=font, fill=INK, anchor="ls")


def _draw_body(
    draw: ImageDraw.ImageDraw, text: str, *, language: str, brackets: bool
) -> None:
    """Lay out the main text, vertically centred between rule and footer."""
    step = size_step(text)
    size, line_height = QUOTE_TYPE[(language if language == "en" else "ja", step)]
    font = _font(size)
    body = f"「{text}」" if brackets else text

    # og.html hangs the opening bracket with text-indent:-.5em. Keep the hang,
    # but never let it reach the indigo hairline.
    first_x = max(CONTENT_LEFT - size / 2, HAIRLINE_X + 8) if brackets else CONTENT_LEFT
    limits = [CONTENT_RIGHT - first_x, CONTENT_RIGHT - CONTENT_LEFT]
    lines = _wrap(font, body, limits)

    line_step = size * line_height
    top = BODY_TOP + (BODY_BOTTOM - BODY_TOP - line_step * len(lines)) / 2
    for index, line in enumerate(lines):
        x = first_x if index == 0 else CONTENT_LEFT
        draw.text((x, top + line_step * index), line, font=font, fill=INK, anchor="la")


def _to_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_quote_og(*, text: str, language: str, credit: str) -> bytes:
    """Render one quote card: body text in brackets, credit, brand."""
    body = truncate_to_width(normalize_og_text(text))
    image, draw = _canvas()
    _draw_body(draw, body, language=language, brackets=True)
    _draw_credit(draw, normalize_og_text(credit) or UNKNOWN_CREDIT, prefix=True)
    _draw_brand(draw)
    return _to_png(image)


def render_author_og(*, name: str) -> bytes:
    """Render one author card: the name, a fixed subtitle, brand."""
    body = truncate_to_width(normalize_og_text(name))
    image, draw = _canvas()
    _draw_body(draw, body, language="ja", brackets=False)
    _draw_credit(draw, AUTHOR_SUBTITLE, prefix=False)
    _draw_brand(draw)
    return _to_png(image)


def render_default_og() -> bytes:
    """Render the shared card used as the site-wide fallback OG image."""
    image, draw = _canvas()
    _draw_body(draw, DEFAULT_OG_TEXT, language="ja", brackets=False)
    _draw_brand(draw)
    return _to_png(image)
