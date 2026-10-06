import hashlib
import logging
import sqlite3
from urllib.error import HTTPError, URLError

import pytest

from app import config
from scripts import backup_sqlite as cli
from tests.test_heartbeat import Response


@pytest.fixture(autouse=True)
def environment(monkeypatch, tmp_path):
    for name, value in {
        "BACKUP_R2_ENDPOINT": "https://r2.example/",
        "BACKUP_R2_BUCKET": "backups",
        "BACKUP_R2_PREFIX": "daily/",
        "BACKUP_R2_ACCESS_KEY_ID": "example-key",
        "BACKUP_R2_SECRET_ACCESS_KEY": "secret-key",
        "UPTIMEROBOT_BACKUP_HEARTBEAT_URL": "https://heartbeat.example/private-token",
    }.items():
        monkeypatch.setenv(name, value)
    db = tmp_path / "source.db"
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE example (value TEXT)")
        connection.executemany("INSERT INTO example VALUES (?)", [("a",), ("b",)])
        connection.commit()
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
        temporary = tmp_path / "temporary"
        temporary.mkdir()
        monkeypatch.setattr(cli.tempfile, "tempdir", str(temporary))
        yield db, temporary
    assert list(temporary.iterdir()) == []


def test_official_aws_put_signature():
    payload_hash = hashlib.sha256(b"Welcome to Amazon S3.").hexdigest()
    result = cli.sign_put(
        "/test%24file.text",
        {
            "date": "Fri, 24 May 2013 00:00:00 GMT",
            "host": "examplebucket.s3.amazonaws.com",
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": "20130524T000000Z",
            "x-amz-storage-class": "REDUCED_REDUNDANCY",
        },
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        timestamp="20130524T000000Z",
        region="us-east-1",
    )
    assert result.endswith(
        "Signature=98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd"
    )


def test_online_copy_contains_committed_wal_rows(environment, tmp_path):
    db, _ = environment
    target = tmp_path / "copy.db"
    cli.backup_database(target)
    with sqlite3.connect(db) as source, sqlite3.connect(target) as backup:
        assert (
            backup.execute("SELECT * FROM example").fetchall()
            == source.execute("SELECT * FROM example").fetchall()
        )
        assert backup.execute("SELECT count(*) FROM example").fetchone() == (2,)
        assert backup.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


@pytest.mark.parametrize("endpoint", ["https://r2.example", "https://r2.example/"])
def test_success_upload_before_heartbeat(monkeypatch, tmp_path, caplog, endpoint):
    monkeypatch.setenv("BACKUP_R2_ENDPOINT", endpoint)
    calls = []

    def open_request(request, *, timeout):
        calls.append("put")
        assert request.get_method() == "PUT"
        assert request.full_url.startswith("https://r2.example/backups/daily/app-")
        assert request.full_url.endswith("Z.db")
        assert timeout == 60
        assert request.get_header("Host") == "r2.example"
        assert request.get_header("Content-length") == str(len(request.data))
        assert (
            request.get_header("X-amz-content-sha256")
            == hashlib.sha256(request.data).hexdigest()
        )
        assert (
            "SignedHeaders=host;x-amz-content-sha256;x-amz-date"
            in request.get_header("Authorization")
        )
        received = tmp_path / "received.db"
        received.write_bytes(request.data)
        with sqlite3.connect(received) as backup:
            assert backup.execute("SELECT count(*) FROM example").fetchone() == (2,)
        return Response()

    def ping(job, url):
        assert job == "backup_sqlite"
        assert url == "https://heartbeat.example/private-token"
        calls.append("heartbeat")

    monkeypatch.setattr(cli, "urlopen", open_request)
    monkeypatch.setattr(cli, "send_heartbeat", ping)
    with caplog.at_level(logging.INFO):
        assert cli.main() == 0
    assert calls == ["put", "heartbeat"]
    assert "key=daily/app-" in caplog.text
    assert "bytes=" in caplog.text and "duration_seconds=" in caplog.text
    assert "secret-key" not in caplog.text
    assert "private-token" not in caplog.text


@pytest.mark.parametrize(
    "failure", ["integrity", "http", "timeout", "network", "missing-db"]
)
def test_failures_skip_heartbeat_and_cleanup(monkeypatch, caplog, environment, failure):
    def unexpected(*_args, **_kwargs):
        pytest.fail("heartbeat must not be sent")

    monkeypatch.setattr(cli, "send_heartbeat", unexpected)
    if failure == "integrity":
        original_connect = cli.sqlite3.connect

        class BadTarget:
            def __init__(self, connection):
                self.connection = connection

            def backup(self, target):
                self.connection.backup(target.connection)

            def execute(self, query):
                assert query == "PRAGMA integrity_check"
                return self

            def fetchall(self):
                return [("ok",), ("corruption",)]

            def close(self):
                self.connection.close()

        monkeypatch.setattr(
            cli.sqlite3, "connect", lambda *a, **k: BadTarget(original_connect(*a, **k))
        )
        monkeypatch.setattr(cli, "urlopen", unexpected)
    elif failure == "missing-db":
        db, _ = environment
        missing = db.with_name("absent.db")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{missing}")
        monkeypatch.setattr(cli, "urlopen", unexpected)
    else:

        def fail(*_args, **_kwargs):
            errors = {
                "http": HTTPError("https://r2.example", 500, "secret-key", {}, None),
                "timeout": TimeoutError("secret-key"),
                "network": URLError("secret-key"),
            }
            raise errors[failure]

        monkeypatch.setattr(cli, "urlopen", fail)
    assert cli.main() != 0
    assert "backup failed" in caplog.text
    assert "secret-key" not in caplog.text
    if failure == "integrity":
        assert "backup integrity_check failed" in caplog.text
    if failure == "missing-db":
        assert "unable to open database file" in caplog.text
        assert not missing.exists()


def test_missing_configuration_fails_before_copy(monkeypatch, caplog):
    missing = [
        "BACKUP_R2_ENDPOINT",
        "BACKUP_R2_BUCKET",
        "BACKUP_R2_ACCESS_KEY_ID",
        "BACKUP_R2_SECRET_ACCESS_KEY",
    ]
    for name in missing:
        monkeypatch.delenv(name)

    def unexpected(*_args, **_kwargs):
        pytest.fail("no copy or HTTP expected")

    for name in ("backup_database", "urlopen", "send_heartbeat"):
        monkeypatch.setattr(cli, name, unexpected)
    assert cli.main() != 0
    for name in missing:
        assert name in caplog.text


def test_prefix_default_only_when_unset(monkeypatch):
    monkeypatch.delenv("BACKUP_R2_PREFIX")
    assert config.get_backup_r2_prefix() == "daily/"
    monkeypatch.setenv("BACKUP_R2_PREFIX", "")
    assert config.get_backup_r2_prefix() == ""


@pytest.mark.parametrize(
    "name",
    [
        "BACKUP_R2_ENDPOINT",
        "BACKUP_R2_BUCKET",
        "BACKUP_R2_ACCESS_KEY_ID",
        "BACKUP_R2_SECRET_ACCESS_KEY",
    ],
)
def test_each_required_setting_is_checked(monkeypatch, caplog, name):
    monkeypatch.delenv(name)
    monkeypatch.setattr(cli, "backup_database", lambda *_a: pytest.fail("copy"))
    assert cli.main() == 1
    assert f"missing {name}" in caplog.text


def test_backup_heartbeat_failure_keeps_success(monkeypatch):
    from app.services import heartbeat

    monkeypatch.setattr(cli, "urlopen", lambda *_a, **_k: Response())

    def fail(*_a, **_k):
        raise TimeoutError("private-token")

    monkeypatch.setattr(heartbeat, "urlopen", fail)
    assert cli.main() == 0


@pytest.mark.parametrize("message", ["database is locked", "disk I/O error"])
def test_sqlite_failure_reason_is_logged(monkeypatch, caplog, message):
    def fail(_destination):
        raise sqlite3.OperationalError(message)

    monkeypatch.setattr(cli, "backup_database", fail)
    monkeypatch.setattr(cli, "send_heartbeat", lambda *_a: pytest.fail("heartbeat"))
    assert cli.main() == 1
    assert message in caplog.text


def test_local_configuration_failure_reason_is_logged(monkeypatch, caplog):
    monkeypatch.setenv("BACKUP_R2_ENDPOINT", "https://r2.example/private-token")
    assert cli.main() == 1
    assert "invalid BACKUP_R2_ENDPOINT" in caplog.text
    assert "private-token" not in caplog.text


def test_library_value_error_does_not_leak_endpoint(monkeypatch, caplog):
    # urlsplit includes the netloc in its NFKC normalization error message.
    monkeypatch.setenv("BACKUP_R2_ENDPOINT", "https://private-token／r2.example")
    assert cli.main() == 1
    assert "ValueError" in caplog.text
    assert "private-token" not in caplog.text
