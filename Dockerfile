# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.16 AS uv

FROM python:3.14-slim

ARG TARGETARCH
ARG CLOUDFLARED_VERSION=2026.9.3
ARG SUPERCRONIC_VERSION=0.2.48

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        fontconfig \
        fonts-noto-cjk \
        fonts-noto-cjk-extra \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

RUN case "${TARGETARCH}" in \
        amd64) \
            cloudflared_sha256="77e26d8d900e0b8469f416239d14b5f296525fdf79fee6f511ef55609e3fbac2"; \
            supercronic_sha256="88c1b66b94c486f972fdd1a4d1f901e3e75ff04f749cddd60c5db573e3a33c6c" \
            ;; \
        arm64) \
            cloudflared_sha256="aaeb2d7d0da3614634c7e03ab13487a1522c2e79165ed2929cfe23d5e95b326d"; \
            supercronic_sha256="50ae8755e04fa72812d0a1bc47a112a856811cc91cce7b6c875c378a850788bc" \
            ;; \
        *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl --fail --location --show-error --silent \
        --output /usr/local/bin/cloudflared \
        "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${TARGETARCH}" \
    && echo "${cloudflared_sha256}  /usr/local/bin/cloudflared" | sha256sum --check --strict \
    && curl --fail --location --show-error --silent \
        --output /usr/local/bin/supercronic \
        "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
    && echo "${supercronic_sha256}  /usr/local/bin/supercronic" | sha256sum --check --strict \
    && chmod 0755 /usr/local/bin/cloudflared /usr/local/bin/supercronic

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
COPY docker/supervisord.conf /etc/supervisor/supervisord.conf
COPY docker/crontab /etc/supercronic/crontab
COPY docker/entrypoint.sh /usr/local/bin/entrypoint

RUN selected_font="$(.venv/bin/python -c \
        'from app.services.og_image import _font_file; print(_font_file()[0])')" \
    && test "${selected_font}" = "/usr/share/fonts/opentype/noto/NotoSerifCJK-SemiBold.ttc" \
    && .venv/bin/python -c \
        'from PIL import ImageFont; from app.services.og_image import _font_file; p,i=_font_file(); assert ImageFont.truetype(p,20,index=i).getname() == ("Noto Serif CJK JP", "SemiBold"); print(f"OG font: {p} face={i} Noto Serif CJK JP SemiBold")' \
    && fc-match --format='%{family}\n%{style}\n%{file}\n' ':lang=ja:family=serif' \
        | grep --quiet --fixed-strings 'Noto Serif CJK JP' \
    && chmod 0755 /usr/local/bin/entrypoint \
    && mkdir -p /data

ENTRYPOINT ["/usr/local/bin/entrypoint"]
