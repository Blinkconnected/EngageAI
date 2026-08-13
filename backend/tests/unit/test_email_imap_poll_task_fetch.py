"""Unit tests for the IMAP fetch-and-mark-seen loop in isolation, against
a fake ``imaplib`` client — the synchronous half of the IMAP poll task
that runs on a worker thread via ``anyio.to_thread.run_sync``. See
``docs/architecture/email-channel.md``.
"""

import imaplib
from typing import Any

import pytest

from blinkengage.infrastructure.tasks.email_imap_poll_task import (
    _fetch_unseen_sync,
    _mark_seen_sync,
)


class _FakeIMAP:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.logged_in = False
        self.selected_folder: str | None = None
        self.stored: list[tuple[str, str]] = []
        self.logged_out = False
        self.closed = False

    def login(self, username: str, password: str) -> None:
        self.logged_in = True

    def select(self, folder: str) -> None:
        self.selected_folder = folder

    def search(self, charset: None, criterion: str) -> tuple[str, list[bytes]]:
        return "OK", [b"1 2"]

    def fetch(self, uid: bytes, parts: str) -> tuple[str, list[Any]]:
        return "OK", [(uid, f"raw-message-{uid.decode()}".encode())]

    def store(self, uid: str, flag_cmd: str, flags: str) -> None:
        self.stored.append((uid, flags))

    def close(self) -> None:
        self.closed = True

    def logout(self) -> None:
        self.logged_out = True


class _EmptyIMAP(_FakeIMAP):
    def search(self, charset: None, criterion: str) -> tuple[str, list[bytes]]:
        return "OK", [b""]


def test_fetch_unseen_sync_fetches_without_acknowledging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fetching must not mark anything ``\\Seen``.

    This used to acknowledge inside the fetch loop and call that the
    idempotency mechanism, which meant a crash between reading a message and
    persisting it lost the message permanently with nothing recording that it
    had arrived. Acknowledgement now happens in ``_mark_seen_sync``, after the
    row is durable — so the flag is an optimisation and the database is the
    system of record.
    """
    created: list[_FakeIMAP] = []

    def factory(host: str, port: int) -> _FakeIMAP:
        instance = _FakeIMAP(host, port)
        created.append(instance)
        return instance

    monkeypatch.setattr(imaplib, "IMAP4_SSL", factory)

    fetched = _fetch_unseen_sync("imap.example.com", 993, "user", "pass", True, "INBOX")

    # ``(uid, raw)`` pairs, so the caller can acknowledge precisely what it
    # managed to store rather than the whole batch.
    assert fetched == [(b"1", b"raw-message-1"), (b"2", b"raw-message-2")]
    connection = created[0]
    assert connection.logged_in is True
    assert connection.selected_folder == "INBOX"
    assert connection.stored == [], "fetch must not acknowledge before persistence"
    assert connection.closed is True
    assert connection.logged_out is True


def test_mark_seen_sync_acknowledges_only_what_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeIMAP] = []

    def factory(host: str, port: int) -> _FakeIMAP:
        instance = _FakeIMAP(host, port)
        created.append(instance)
        return instance

    monkeypatch.setattr(imaplib, "IMAP4_SSL", factory)

    _mark_seen_sync("imap.example.com", 993, "user", "pass", True, "INBOX", [b"1"])

    assert created[0].stored == [("1", "\\Seen")]


def test_mark_seen_sync_does_not_connect_for_an_empty_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing stored means nothing to acknowledge, and no reason to log in."""
    created: list[_FakeIMAP] = []

    def factory(host: str, port: int) -> _FakeIMAP:
        instance = _FakeIMAP(host, port)
        created.append(instance)
        return instance

    monkeypatch.setattr(imaplib, "IMAP4_SSL", factory)

    _mark_seen_sync("imap.example.com", 993, "user", "pass", True, "INBOX", [])

    assert created == []


def test_fetch_unseen_sync_returns_empty_when_no_unseen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port: _EmptyIMAP(host, port))

    messages = _fetch_unseen_sync("imap.example.com", 993, "user", "pass", True, "INBOX")

    assert messages == []


def test_fetch_unseen_sync_uses_plain_imap4_when_ssl_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeIMAP] = []

    def factory(host: str, port: int) -> _FakeIMAP:
        instance = _FakeIMAP(host, port)
        created.append(instance)
        return instance

    # ``_fetch_unseen_sync`` always references ``imaplib.IMAP4.error`` in its
    # cleanup (even on the SSL path, since ``IMAP4_SSL`` inherits it) — keep
    # that attribute present on the patched callable so the real class isn't
    # needed for this test.
    factory.error = imaplib.IMAP4.error  # type: ignore[attr-defined]
    monkeypatch.setattr(imaplib, "IMAP4", factory)

    messages = _fetch_unseen_sync("imap.example.com", 143, "user", "pass", False, "INBOX")

    assert len(messages) == 2
    assert created[0].host == "imap.example.com"
