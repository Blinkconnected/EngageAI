"""Attachments on the platform's own transactional mail — the structure
of the message that goes on the wire, without a relay in sight.

Two of these assertions are regressions waiting to happen rather than
feature tests. **A message with no attachments must still be a
single-part plain-text message**: notifications, dunning notices and
verification mail all go through here, and a multipart envelope added
"just in case" changes what every one of those recipients' clients
renders. And **a filename is never trusted**: it comes from a document
number, a company name somebody typed, or an uploaded file, and it ends
up both inside a header and as a path on somebody's disk.

The relay itself is out of scope here, as it is everywhere else in this
suite (see ``tests/unit/test_email_provider.py``): ``aiosmtplib.send`` is
monkeypatched where a send has to be observed at all.
"""

from typing import Any

import pytest

from blinkengage.domain.mail import MailConfig, MailSecurity
from blinkengage.infrastructure.email.mailer import (
    FALLBACK_FILENAME,
    MAX_TOTAL_ATTACHMENT_BYTES,
    Attachment,
    AttachmentTooLargeError,
    MailDeliveryError,
    build_message,
    sanitise_filename,
    send_with_config,
)

CONFIG = MailConfig(
    host="mail.internal",
    port=25,
    security=MailSecurity.NONE,
    from_address="billing@example.test",
    from_name="Blink Engage",
)

INVOICE_PDF = Attachment(
    filename="INV-2026-000001.pdf",
    content_type="application/pdf",
    data=b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n",
)


def _message(
    *, body: str = "Your invoice is attached.", attachments: list[Attachment] | None = None
) -> Any:
    return build_message(
        CONFIG,
        to_address="ap@customer.test",
        subject="Invoice INV-2026-000001",
        body=body,
        attachments=attachments or [],
    )


class TestWithoutAttachments:
    """The shape every existing caller already depends on."""

    def test_the_message_stays_plain_text(self) -> None:
        """Not ``multipart/mixed`` with a single text part — a genuinely
        single-part ``text/plain`` message, byte for byte what this
        module sent before attachments existed."""
        message = _message()

        assert message.is_multipart() is False
        assert message.get_content_type() == "text/plain"
        assert message.get_content().strip() == "Your invoice is attached."

    def test_the_headers_are_unchanged(self) -> None:
        message = _message()

        assert message["From"] == "Blink Engage <billing@example.test>"
        assert message["To"] == "ap@customer.test"
        assert message["Subject"] == "Invoice INV-2026-000001"

    def test_an_empty_sequence_is_the_same_as_omitting_it(self) -> None:
        """``attachments=[]`` is what a caller building a list ends up
        passing, and it must not promote the message either."""
        assert (
            build_message(
                CONFIG, to_address="a@b.test", subject="s", body="b", attachments=[]
            ).is_multipart()
            is False
        )

    async def test_the_relay_receives_a_plain_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: dict[str, Any] = {}

        async def fake_send(message: Any, **kwargs: Any) -> tuple[Any, Any]:
            sent["message"] = message
            return None, None

        monkeypatch.setattr("blinkengage.infrastructure.email.mailer.aiosmtplib.send", fake_send)

        await send_with_config(
            CONFIG, to_address="agent@example.test", subject="Assigned", body="Take a look."
        )

        assert sent["message"].is_multipart() is False
        assert sent["message"].get_content_type() == "text/plain"


class TestWithAttachments:
    def test_the_message_becomes_multipart_with_the_body_intact(self) -> None:
        message = _message(attachments=[INVOICE_PDF])

        assert message.get_content_type() == "multipart/mixed"
        body = message.get_body(preferencelist=("plain",))
        assert body is not None
        assert body.get_content().strip() == "Your invoice is attached."

    def test_the_attachment_keeps_its_bytes_type_and_name(self) -> None:
        parts = list(_message(attachments=[INVOICE_PDF]).iter_attachments())

        assert len(parts) == 1
        assert parts[0].get_content_type() == "application/pdf"
        assert parts[0].get_filename() == "INV-2026-000001.pdf"
        assert parts[0].get_payload(decode=True) == INVOICE_PDF.data
        # Binary must not travel as 8bit: a relay is entitled to mangle a
        # bare NUL or a long line, and a mangled PDF opens nowhere.
        assert parts[0]["Content-Transfer-Encoding"] == "base64"

    def test_each_attachment_gets_its_own_part(self) -> None:
        credit_note = Attachment(
            filename="CN-2026-000001.pdf", content_type="application/pdf", data=b"%PDF-1.7 cn"
        )
        parts = list(_message(attachments=[INVOICE_PDF, credit_note]).iter_attachments())

        assert [part.get_filename() for part in parts] == [
            "INV-2026-000001.pdf",
            "CN-2026-000001.pdf",
        ]

    def test_a_declared_type_that_is_not_one_becomes_unknown_bytes(self) -> None:
        """``application/octet-stream`` is the honest answer, and every
        client offers it as a download rather than guessing. The
        alternative is an unvalidated string written straight into a
        header."""
        parts = list(
            _message(
                attachments=[Attachment(filename="x.bin", content_type="not a type", data=b"..")]
            ).iter_attachments()
        )

        assert parts[0].get_content_type() == "application/octet-stream"


class TestFilenames:
    def test_a_path_is_reduced_to_its_last_segment(self) -> None:
        """Some clients still join an attachment's name onto a download
        directory, and the one that does is the one that matters."""
        assert sanitise_filename("../../etc/passwd") == "passwd"
        assert sanitise_filename("C:\\Windows\\System32\\evil.dll") == "evil.dll"

    def test_a_header_injection_attempt_never_reaches_the_headers(self) -> None:
        """A newline in a header value ends that header — everything
        after it is parsed as the next one, which is a ``Bcc:`` of the
        attacker's choosing on a message the platform's own relay has
        already authenticated."""
        message = _message(
            attachments=[
                Attachment(
                    filename="invoice.pdf\r\nBcc: attacker@example.test",
                    content_type="application/pdf",
                    data=b"%PDF-1.7",
                )
            ]
        )
        raw = bytes(message)

        assert b"Bcc:" not in raw
        assert message["Bcc"] is None
        name = list(message.iter_attachments())[0].get_filename()
        assert name is not None
        assert "\r" not in name and "\n" not in name

    def test_a_right_to_left_override_is_removed(self) -> None:
        """U+202E reverses everything after it, so this renders to the eye
        as ``invoiceexe.pdf``. It is a display attack rather than a
        parsing one, so correct header encoding does nothing about it."""
        assert sanitise_filename("invoice\u202efdp.exe") == "invoicefdp.exe"

    def test_a_name_with_nothing_usable_left_falls_back(self) -> None:
        """A part with no filename is saved as "noname" by most clients
        and cannot be told apart from any other attachment."""
        assert sanitise_filename("") == FALLBACK_FILENAME
        assert sanitise_filename("...") == FALLBACK_FILENAME
        assert sanitise_filename("/") == FALLBACK_FILENAME

    def test_a_leading_dot_is_stripped(self) -> None:
        assert sanitise_filename(".hidden.pdf") == "hidden.pdf"

    def test_a_long_name_is_trimmed_but_keeps_its_extension(self) -> None:
        """The extension is what the recipient's client keys "open with"
        off; a name truncated to ``INV-2026`` opens in nothing."""
        trimmed = sanitise_filename("و" * 400 + ".pdf")

        assert trimmed.endswith(".pdf")
        # Bytes, not characters: an Arabic name is two bytes per
        # character, and 255 is a byte limit on every filesystem.
        assert len(trimmed.encode()) <= 200


class TestNonAscii:
    """Arabic customer names, filenames and bodies. The existing code
    already carries UTF-8 subjects and bodies; attaching a file must not
    be the thing that breaks it."""

    def test_an_arabic_filename_arrives_intact(self) -> None:
        arabic = "فاتورة-٢٠٢٦.pdf"
        message = _message(
            attachments=[
                Attachment(filename=arabic, content_type="application/pdf", data=b"%PDF-1.7")
            ]
        )

        assert list(message.iter_attachments())[0].get_filename() == arabic
        # Carried by RFC 2231 — percent-encoded, possibly split across
        # continuations — rather than as raw UTF-8 bytes in a header,
        # which is what an older relay would mangle into mojibake.
        raw = bytes(message)
        assert b"utf-8''" in raw
        assert arabic.encode() not in raw

    def test_an_arabic_body_survives_beside_an_attachment(self) -> None:
        arabic_body = "مرحباً، فاتورتك مرفقة."
        message = _message(body=arabic_body, attachments=[INVOICE_PDF])
        body = message.get_body(preferencelist=("plain",))

        assert body is not None
        assert body.get_content().strip() == arabic_body
        assert body.get_content_charset() == "utf-8"


class TestSizeLimit:
    def test_a_message_at_the_cap_is_accepted(self) -> None:
        at_the_cap = Attachment(
            filename="big.pdf",
            content_type="application/pdf",
            data=b"\0" * MAX_TOTAL_ATTACHMENT_BYTES,
        )

        assert len(list(_message(attachments=[at_the_cap]).iter_attachments())) == 1

    def test_the_cap_is_the_total_not_each_file(self) -> None:
        """A relay limits the message, not the part — three files half
        the cap each is an oversized message however it is counted."""
        half = MAX_TOTAL_ATTACHMENT_BYTES // 2 + 1
        oversized = [
            Attachment(filename=f"{index}.pdf", content_type="application/pdf", data=b"\0" * half)
            for index in range(2)
        ]

        with pytest.raises(AttachmentTooLargeError):
            _message(attachments=oversized)

    def test_the_refusal_names_the_size(self) -> None:
        """An operator reading this must be able to tell it from a relay
        outage without opening the code."""
        with pytest.raises(AttachmentTooLargeError) as refused:
            _message(
                attachments=[
                    Attachment(
                        filename="big.pdf",
                        content_type="application/pdf",
                        data=b"\0" * (MAX_TOTAL_ATTACHMENT_BYTES + 1),
                    )
                ]
            )

        assert "MiB" in str(refused.value)
        # Not a delivery failure: nothing was delivered because nothing
        # was sent, and reporting it as one sends somebody to investigate
        # a relay that never saw the message.
        assert not isinstance(refused.value, MailDeliveryError)

    async def test_an_oversized_message_never_reaches_the_relay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failing at send time costs a connection, an authentication and
        the whole upload before the relay says no — and says it as a
        generic delivery failure."""

        async def fail_if_called(message: Any, **kwargs: Any) -> tuple[Any, Any]:
            raise AssertionError("the relay must not be contacted for an oversized message")

        monkeypatch.setattr(
            "blinkengage.infrastructure.email.mailer.aiosmtplib.send", fail_if_called
        )

        with pytest.raises(AttachmentTooLargeError):
            await send_with_config(
                CONFIG,
                to_address="ap@customer.test",
                subject="Invoice",
                body="Attached.",
                attachments=[
                    Attachment(
                        filename="big.pdf",
                        content_type="application/pdf",
                        data=b"\0" * (MAX_TOTAL_ATTACHMENT_BYTES + 1),
                    )
                ],
            )


class TestDelivery:
    async def test_attachments_reach_the_relay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent: dict[str, Any] = {}

        async def fake_send(message: Any, **kwargs: Any) -> tuple[Any, Any]:
            sent["message"] = message
            sent["kwargs"] = kwargs
            return None, None

        monkeypatch.setattr("blinkengage.infrastructure.email.mailer.aiosmtplib.send", fake_send)

        await send_with_config(
            CONFIG,
            to_address="ap@customer.test",
            subject="Invoice INV-2026-000001",
            body="Your invoice is attached.",
            attachments=[INVOICE_PDF],
        )

        parts = list(sent["message"].iter_attachments())
        assert [part.get_filename() for part in parts] == ["INV-2026-000001.pdf"]
        assert sent["kwargs"]["hostname"] == "mail.internal"
        assert sent["kwargs"]["start_tls"] is False

    async def test_a_relay_failure_is_still_a_delivery_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unchanged by attachments: the relay's own words are what an
        operator needs, and they only exist on this path."""

        async def failing_send(message: Any, **kwargs: Any) -> tuple[Any, Any]:
            raise ConnectionError("relay unreachable")

        monkeypatch.setattr("blinkengage.infrastructure.email.mailer.aiosmtplib.send", failing_send)

        with pytest.raises(MailDeliveryError, match="relay unreachable"):
            await send_with_config(
                CONFIG,
                to_address="ap@customer.test",
                subject="Invoice",
                body="Attached.",
                attachments=[INVOICE_PDF],
            )
