"""Render the site-wide fallback OG image into app/static/.

The file is committed because it must exist even when OG rendering fails (for
example when the Japanese font is missing), so it cannot be produced on demand.
Re-run this only when the OG design changes; the printed file name goes into
``app/templates/base.html``.

Usage: uv run python scripts/build_default_og.py
"""

import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.og_image import render_default_og

STATIC_DIR = PROJECT_ROOT / "app" / "static"
PREFIX = "og-default."


def main() -> None:
    png = render_default_og()
    digest = hashlib.sha256(png).hexdigest()[:8]
    target = STATIC_DIR / f"{PREFIX}{digest}.png"
    for stale in STATIC_DIR.glob(f"{PREFIX}*.png"):
        if stale != target:
            stale.unlink()
    target.write_bytes(png)
    print(target.name)


if __name__ == "__main__":
    main()
