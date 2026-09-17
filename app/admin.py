"""Small shared building blocks for the administration interface."""

import hashlib
import hmac
import logging
import re
import time
from datetime import UTC, datetime
from functools import lru_cache
from json import JSONDecodeError
from urllib.parse import parse_qs, urlsplit

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
    PyJWTError,
)

from app.config import (
    get_admin_dev_email,
    get_cf_access_aud,
    get_cf_access_team_domain,
    get_public_origin,
    get_secret_key,
)

logger = logging.getLogger("app.admin")

DEFAULT_FORM_MAX_BYTES = 1024 * 1024
CSRF_MAX_AGE_SECONDS = 12 * 60 * 60
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _forbidden(reason: str) -> None:
    logger.warning("admin authentication rejected: %s", reason)
    raise HTTPException(status_code=403, detail="Forbidden")


def _dev_admin_email() -> str | None:
    email = get_admin_dev_email()
    try:
        host = urlsplit(get_public_origin()).hostname
    except ValueError:
        return None
    if email and get_cf_access_aud() is None and host in {"localhost", "127.0.0.1"}:
        return email
    return None


@lru_cache(maxsize=1)
def _get_jwk_client(team_domain: str) -> PyJWKClient:
    """Create the network-backed key client only when authentication needs it."""
    return PyJWKClient(f"{team_domain}/cdn-cgi/access/certs")


def require_admin(request: Request) -> str:
    """Validate a Cloudflare Access assertion and return its administrator email."""
    dev_email = _dev_admin_email()
    if dev_email is not None:
        return dev_email

    try:
        team_domain = get_cf_access_team_domain()
        audience = get_cf_access_aud()
    except ValueError:
        _forbidden("required configuration invalid")
    if not team_domain or not audience or not get_secret_key():
        _forbidden("required configuration missing")

    token = request.headers.get("Cf-Access-Jwt-Assertion")
    if not token:
        _forbidden("assertion missing")

    try:
        signing_key = _get_jwk_client(team_domain).get_signing_key_from_jwt(token)
    except InvalidTokenError:
        _forbidden("signature invalid")
    except PyJWTError, JSONDecodeError, UnicodeDecodeError:
        _forbidden("signing key retrieval failed")

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=team_domain,
            options={"require": ["exp"]},
        )
    except ExpiredSignatureError:
        _forbidden("assertion expired")
    except InvalidAudienceError:
        _forbidden("audience invalid")
    except InvalidIssuerError:
        _forbidden("issuer invalid")
    except InvalidSignatureError:
        _forbidden("signature invalid")
    except MissingRequiredClaimError as error:
        missing_claim_reasons = {
            "aud": "audience missing",
            "iss": "issuer missing",
            "exp": "expiration missing",
        }
        _forbidden(missing_claim_reasons.get(error.claim, "required claim missing"))
    except InvalidTokenError:
        _forbidden("assertion invalid")

    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        _forbidden("email invalid")
    return email


def issue_csrf_token(email: str, *, now: int | None = None) -> str:
    """Issue a stateless CSRF token bound to one authenticated email."""
    secret = get_secret_key()
    if not secret:
        raise RuntimeError("SECRET_KEY is required")
    issued_at = int(time.time()) if now is None else now
    signature = hmac.new(
        secret.encode(),
        f"{email}|{issued_at}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{issued_at}.{signature}"


def validate_csrf_token(token: str, email: str, *, now: int | None = None) -> bool:
    """Return whether a CSRF token is authentic, current, and email-bound."""
    secret = get_secret_key()
    if not secret:
        return False
    try:
        issued_text, supplied = token.split(".", 1)
        issued_at = int(issued_text)
    except AttributeError, TypeError, ValueError:
        return False
    if issued_text != str(issued_at):
        return False
    current = int(time.time()) if now is None else now
    if issued_at > current or current - issued_at > CSRF_MAX_AGE_SECONDS:
        return False
    expected = hmac.new(
        secret.encode(),
        f"{email}|{issued_at}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(supplied, expected)


async def read_urlencoded_form(
    request: Request, *, max_bytes: int = DEFAULT_FORM_MAX_BYTES
) -> dict[str, list[str]]:
    """Read a bounded URL-encoded form while preserving repeated values."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if media_type != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="unsupported content type")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise HTTPException(status_code=413, detail="request body too large")
        body.extend(chunk)
    try:
        encoded = bytes(body).decode("ascii")
        if _INVALID_PERCENT_ESCAPE.search(encoded):
            raise ValueError("invalid percent escape")
        return parse_qs(
            encoded,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=1000,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="invalid form body") from error


def require_csrf(form: dict[str, list[str]], email: str) -> None:
    """Reject a parsed form unless it has exactly one valid CSRF token."""
    values = form.get("csrf_token", [])
    if len(values) != 1 or not validate_csrf_token(values[0], email):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def log_admin_operation(
    email: str, action: str, target: str, *, now: datetime | None = None
) -> None:
    """Write one compact operation record to the administration logger."""
    occurred_at = now or datetime.now(UTC)

    def one_line(value: str) -> str:
        return " ".join(value.split())

    logger.info(
        "admin_email=%s action=%s target=%s at=%s",
        one_line(email),
        one_line(action),
        one_line(target),
        occurred_at.astimezone(UTC).isoformat(),
    )
