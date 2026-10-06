"""Online SQLite backup, integrity check, and one signed R2 PUT."""

import hashlib
import hmac
import logging
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from http.client import HTTPException as HTTPClientException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import (
    get_backup_r2_access_key_id,
    get_backup_r2_bucket,
    get_backup_r2_endpoint,
    get_backup_r2_prefix,
    get_backup_r2_secret_access_key,
    get_database_url,
    get_uptimerobot_backup_heartbeat_url,
)
from app.services.heartbeat import send_heartbeat

logger = logging.getLogger("backup_sqlite")


class BackupValidationError(ValueError):
    """A local validation failure whose message contains no configuration values."""


def sign_put(
    path: str,
    headers: dict[str, str],
    *,
    access_key: str,
    secret_key: str,
    timestamp: str,
    region: str,
    service: str = "s3",
) -> str:
    """Return SigV4 Authorization for a PUT with no query, using explicit inputs."""
    normalized = {k.lower(): " ".join(v.split()) for k, v in headers.items()}
    names = sorted(normalized)
    signed_headers = ";".join(names)
    canonical_headers = "".join(f"{name}:{normalized[name]}\n" for name in names)
    canonical_request = "\n".join(
        [
            "PUT",
            path,
            "",
            canonical_headers,
            signed_headers,
            normalized["x-amz-content-sha256"],
        ]
    )
    date = timestamp[:8]
    scope = f"{date}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            timestamp,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    key = ("AWS4" + secret_key).encode()
    for part in (date, region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


def backup_database(destination: Path) -> None:
    """Open the existing source read-only and verify its online backup."""
    url = make_url(get_database_url())
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        raise BackupValidationError("DATABASE_URL must name an SQLite file")
    source_uri = Path(url.database).resolve().as_uri() + "?mode=ro"
    with (
        closing(sqlite3.connect(source_uri, uri=True)) as source,
        closing(sqlite3.connect(destination)) as target,
    ):
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupValidationError("backup integrity_check failed")


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    started = time.monotonic()
    settings = {
        "BACKUP_R2_ENDPOINT": get_backup_r2_endpoint(),
        "BACKUP_R2_BUCKET": get_backup_r2_bucket(),
        "BACKUP_R2_ACCESS_KEY_ID": get_backup_r2_access_key_id(),
        "BACKUP_R2_SECRET_ACCESS_KEY": get_backup_r2_secret_access_key(),
    }
    missing = [name for name, value in settings.items() if not value]
    if missing:
        logger.error("backup failed: missing %s", ", ".join(missing))
        return 1
    stage = "configuration"
    try:
        endpoint = settings["BACKUP_R2_ENDPOINT"]
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise BackupValidationError("invalid BACKUP_R2_ENDPOINT")
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        key = f"{get_backup_r2_prefix()}app-{timestamp}.db"
        path = quote(f"/{settings['BACKUP_R2_BUCKET']}/{key}", safe="/-.")
        with tempfile.TemporaryDirectory(prefix="backup_sqlite-") as temporary:
            backup_path = Path(temporary) / "app.db"
            stage = "SQLite backup/integrity_check"
            backup_database(backup_path)
            body = backup_path.read_bytes()
            headers = {
                "Host": parsed.netloc,
                "x-amz-date": timestamp,
                "x-amz-content-sha256": hashlib.sha256(body).hexdigest(),
            }
            headers["Authorization"] = sign_put(
                path,
                headers,
                access_key=settings["BACKUP_R2_ACCESS_KEY_ID"],
                secret_key=settings["BACKUP_R2_SECRET_ACCESS_KEY"],
                timestamp=timestamp,
                region="auto",
            )
            headers["Content-Length"] = str(len(body))
            request = Request(endpoint + path, data=body, headers=headers, method="PUT")
            stage = "R2 PUT"
            with urlopen(request, timeout=60):
                pass
            logger.info(
                "backup succeeded key=%s bytes=%d duration_seconds=%.3f",
                key,
                len(body),
                time.monotonic() - started,
            )
            send_heartbeat("backup_sqlite", get_uptimerobot_backup_heartbeat_url())
    except HTTPError as error:
        logger.error("backup failed: PUT HTTP %d", error.code)
        return 1
    except (sqlite3.Error, BackupValidationError) as error:
        logger.error("backup failed stage=%s: %s", stage, error)
        return 1
    except (URLError, HTTPClientException, OSError, ValueError) as error:
        # Network exception messages can contain credentials or signed URLs.
        logger.error("backup failed stage=%s: %s", stage, type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
