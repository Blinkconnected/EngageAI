"""Shared transactional email sender, over the platform's own SMTP relay
— never a company's customer-facing ``EmailProvider`` channel
credentials.

The relay is configured either by environment variable or from the
platform console (see ``docs/architecture/platform-admin.md``); this
module takes a resolved ``MailConfig`` and does not care which produced
it.

``send_plain_email`` keeps its ``Settings``-based signature so existing
callers are untouched, and resolves the environment configuration
itself. Anything that can reach the database should prefer
``send_with_config`` with the resolved configuration, so a relay changed
in the console takes effect without a redeploy.

**A message may carry attachments**, so an invoice PDF can be sent to the
customer it bills. A message *without* them is still exactly what it has
always been: one ``text/plain`` part, no MIME envelope around it. That
distinction is deliberate — the notification, dunning and verification
mail this module has always sent goes to real inboxes, and wrapping every
one of them in ``multipart/mixed`` "just in case" changes what each
recipient's client renders for a feature they are not using.

Two refusals happen **before** the relay is contacted, in
``build_message``: an oversized set of attachments
(``AttachmentTooLargeError``), and a filename that could inject a header
or escape a directory (silently sanitised, since there is a correct name
to fall back to). Both are cheaper to explain here than as an SMTP
rejection after a connection, an authentication and an upload.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Final

import aiosmtplib

from blinkengage.core.config import Settings
from blinkengage.domain.mail import MailConfig, MailSecurity

#: The most one message may carry, summed across its attachments and
#: measured on the raw bytes — *before* transfer encoding.
#:
#: Base64 inflates a payload by a third, so 10 MiB of files leave here as
#: roughly 13.7 MiB on the wire: comfortably inside the 25 MB that Gmail,
#: Microsoft 365 and most corporate relays enforce, with room to spare for
#: headers and body. Sizing the cap against the *encoded* figure is what
#: makes it defensible — a limit set at 25 MiB of raw bytes would produce
#: 34 MiB messages and bounce.
#:
#: Generous for what this exists to carry: an invoice PDF is tens of
#: kilobytes, three orders of magnitude below the cap.
MAX_TOTAL_ATTACHMENT_BYTES: Final[int] = 10 * 1024 * 1024

#: What an attachment is called when sanitising leaves nothing usable.
#: A name is required — a part with no filename is saved as "noname" by
#: most clients and cannot be told apart from any other.
FALLBACK_FILENAME: Final[str] = "attachment"

#: Longest filename put on the wire, in UTF-8 bytes rather than
#: characters: every character of an Arabic name is two bytes, and it is
#: bytes that filesystems (255) and header lines care about.
_MAX_FILENAME_BYTES: Final[int] = 200

#: Characters no mainstream filesystem accepts in a name, plus both path
#: separators. ``:`` is here because on NTFS ``invoice.pdf:payload.exe``
#: names an alternate data stream rather than a file, so a name carrying
#: one does not save where the recipient believes it did.
_RESERVED_FILENAME_CHARACTERS: Final[frozenset[str]] = frozenset('<>:"/\\|?*')

#: RFC 2045 token, which is what a MIME type's halves are allowed to be.
#: Anything else is not a content type, whatever it claims.
_MIME_TOKEN = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")

#: What a part is labelled when its declared type is unusable. "Unknown
#: bytes" is the honest answer, and every client knows to offer it as a
#: download rather than guess.
_FALLBACK_MIME_TYPE: Final[tuple[str, str]] = ("application", "octet-stream")


class MailDeliveryError(RuntimeError):
    """The relay refused the message or could not be reached.

    Carries the relay's own words where there are any — "535
    authentication failed" tells an operator to fix the password, while
    "could not send email" sends them looking at DNS.
    """


class AttachmentTooLargeError(ValueError):
    """More attached bytes than a message may carry.

    Deliberately **not** a ``MailDeliveryError``: nothing was delivered
    because nothing was ever sent, and a caller that reports this as
    "the relay refused it" sends an operator to investigate a relay that
    never saw the message. It is a bad request — the caller is holding
    something too big to email — so a caller at an API boundary should
    answer 422 and say so, not retry.
    """


@dataclass(frozen=True, slots=True)
class Attachment:
    """One file to hang off a message: what it is called, what it is, and
    the bytes themselves.

    Frozen, and holding the bytes rather than a key to fetch them, so a
    message is built from exactly what the caller decided to send. An
    invoice PDF is rendered from a frozen snapshot; a value this module
    could edit — or re-read later and find changed — is a value that can
    disagree with the document it was printed from.

    Field names match ``domain.channels.OutboundAttachment``, which is
    the same idea for the customer-facing channels, so neither has to be
    translated into the other by hand at a call site that has both.
    """

    filename: str
    content_type: str
    data: bytes

    @property
    def safe_filename(self) -> str:
        """The name actually put on the wire — see ``sanitise_filename``."""
        return sanitise_filename(self.filename)


#: Line and paragraph separators. Category "Z" also covers ordinary spaces,
#: which are perfectly fine in a filename — only these two are breaks.
_SEPARATOR_CATEGORIES = frozenset({"Zl", "Zp"})


def sanitise_filename(filename: str) -> str:
    """The name a recipient's client is allowed to see, from one it is not.

    An attachment's name is rarely ours: it is derived from a document
    number, a company name a customer typed, or an uploaded file. It then
    travels inside a ``Content-Disposition`` header and, moments later,
    becomes a path on somebody's disk. Three things must not survive that
    trip:

    * **Line breaks and other control characters.** A newline in a header
      value ends the header, and everything after it is parsed as the
      start of the next one — a ``Bcc:`` of the sender's choosing on a
      message the platform's own relay has already authenticated.
    * **Path separators.** ``../../etc/passwd`` and
      ``C:\\Windows\\System32\\x`` must save as ``passwd`` and ``x``. Some
      clients still join an attachment's name onto a download directory,
      and the one that does is the one that matters.
    * **Bidirectional overrides.** ``U+202E`` reverses everything after
      it, so ``invoice\\u202Efdp.exe`` renders to the eye as
      ``invoiceexe.pdf``. It is a display attack, not a parsing one, so no
      amount of correct header encoding stops it.

    Non-ASCII is emphatically **kept**: a Jordanian customer's invoice is
    named in Arabic, and stripping it to ASCII leaves ``.pdf``. The name
    is carried by RFC 2231 encoding, which ``EmailMessage`` applies for
    us, and arrives at the client intact.
    """
    # Only the last segment survives: everything before a separator is a
    # directory this message has no business naming.
    last_segment = re.split(r"[\\/]", filename)[-1]
    cleaned = "".join(
        character
        for character in last_segment
        if character not in _RESERVED_FILENAME_CHARACTERS
        # Category "C" is every control, format, surrogate and unassigned
        # code point — the whole family, rather than a list of the ones
        # somebody thought of, because it is the unlisted one that gets
        # through. "Zl" and "Zp" are LINE SEPARATOR and PARAGRAPH SEPARATOR:
        # not controls by category, but line breaks by behaviour, and a
        # filename containing one renders as two lines in a mail client.
        and unicodedata.category(character) not in _SEPARATOR_CATEGORIES
        and not unicodedata.category(character).startswith("C")
    )
    # Leading dots hide a file on Unix and are how ".." is spelled;
    # trailing dots and spaces are silently dropped by Windows, which
    # makes "report.pdf " and "report.pdf" the same file to it and two
    # different ones to us.
    # Stripped *again* after the length trim, not only before it. Trimming a
    # short stem with a long extension can leave the tail alone — ".AAAA…" —
    # which re-creates the leading dot the first strip removed, and a
    # dot-prefixed attachment saves as a hidden file on Unix and macOS.
    return _fit_to_length(cleaned.strip(" .")).strip(" .") or FALLBACK_FILENAME


def build_message(
    config: MailConfig,
    *,
    to_address: str,
    subject: str,
    body: str,
    attachments: Sequence[Attachment] = (),
) -> EmailMessage:
    """The message as it will go on the wire.

    With no attachments this is a single-part ``text/plain`` message,
    byte for byte what this function has always produced — see the module
    docstring for why that is a rule and not an accident. The first
    ``add_attachment`` call is what promotes it to ``multipart/mixed``.

    Raises ``AttachmentTooLargeError`` before building anything, so a
    caller learns the message is unsendable without a socket being opened.
    """
    _refuse_oversized(attachments)

    message = EmailMessage()
    message["From"] = f"{config.from_name} <{config.from_address}>"
    message["To"] = to_address
    message["Subject"] = subject
    # Picks UTF-8 and an appropriate transfer encoding on its own when the
    # body is not ASCII, which an Arabic notification never is.
    message.set_content(body)
    for attachment in attachments:
        maintype, subtype = _mime_type(attachment.content_type)
        message.add_attachment(
            attachment.data,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.safe_filename,
        )
    return message


async def send_with_config(
    config: MailConfig,
    *,
    to_address: str,
    subject: str,
    body: str,
    attachments: Sequence[Attachment] = (),
) -> None:
    """Sends one message over the configured relay.

    ``use_tls`` and ``start_tls`` are passed explicitly rather than left
    to aiosmtplib's autodetection: the library will happily fall back to
    an unencrypted session against a relay that does not offer
    STARTTLS, which would put a password on the wire in clear. Being
    explicit turns that into a failure the operator sees.

    ``attachments`` defaults to none, and a caller that omits it sends
    precisely the message it sent before this parameter existed.
    """
    message = build_message(
        config, to_address=to_address, subject=subject, body=body, attachments=attachments
    )
    try:
        await aiosmtplib.send(
            message,
            hostname=config.host,
            port=config.port,
            username=config.username or None,
            password=config.password or None,
            use_tls=config.security is MailSecurity.TLS,
            start_tls=config.security is MailSecurity.STARTTLS,
            timeout=config.timeout_seconds,
        )
    except (aiosmtplib.SMTPException, OSError) as exc:
        raise MailDeliveryError(str(exc) or exc.__class__.__name__) from exc


async def send_plain_email(
    settings: Settings,
    *,
    to_address: str,
    subject: str,
    body: str,
    attachments: Sequence[Attachment] = (),
) -> None:
    """Backwards-compatible entry point for callers with only settings.

    Attachments are accepted here too: a scheduled task holds settings
    and often no session, and making it resolve a ``MailConfig`` by hand
    to attach a file would put a second copy of that resolution in the
    codebase for one caller's benefit.
    """
    from blinkengage.application.services.platform_settings_service import (
        environment_mail_config,
    )

    await send_with_config(
        environment_mail_config(settings),
        to_address=to_address,
        subject=subject,
        body=body,
        attachments=attachments,
    )


def _refuse_oversized(attachments: Sequence[Attachment]) -> None:
    """Stops an unsendable message here rather than at the relay.

    A relay enforces its size limit *after* the connection, the
    authentication and the upload, and reports the refusal as a delivery
    failure indistinguishable from a broken relay — so whoever
    investigates starts at DNS and credentials instead of at the 30 MB
    file. Refused here, the message names its own problem, and does it
    without spending the upload.
    """
    total = sum(len(attachment.data) for attachment in attachments)
    if total > MAX_TOTAL_ATTACHMENT_BYTES:
        raise AttachmentTooLargeError(
            f"Attachments total {total / 1024 / 1024:.1f} MiB; one message may carry "
            f"{MAX_TOTAL_ATTACHMENT_BYTES / 1024 / 1024:.0f} MiB "
            f"({MAX_TOTAL_ATTACHMENT_BYTES:,} bytes) before transfer encoding. "
            f"Send a link to the document instead of the document."
        )


#: Types whose bodies are structurally something else — a multipart needs a
#: boundary, a message/* needs headers. Declared on a base64 blob, either
#: produces MIME a strict parser may reject *whole*, taking the invoice with
#: it. An attachment is a file, so it is treated as one.
_STRUCTURAL_MAINTYPES = frozenset({"multipart", "message"})


def _mime_type(content_type: str) -> tuple[str, str]:
    """The declared type split for ``add_attachment``, or the unknown-bytes
    type when it is not usable.

    Parameters are dropped and the type is lowercased, the same
    normalisation ``domain/media.py`` applies, so ``application/PDF`` and
    ``text/plain; charset=utf-8`` are recognised. Each half is then
    checked against the RFC 2045 token grammar — a content type is
    written into a header exactly as given, so an unvalidated one is the
    same injection surface as an unvalidated filename, and a caller
    guessing "pdf" or "" is a far likelier cause than an attacker.
    """
    maintype, _, subtype = content_type.split(";")[0].strip().lower().partition("/")
    if not _MIME_TOKEN.match(maintype) or not _MIME_TOKEN.match(subtype):
        return _FALLBACK_MIME_TYPE
    if maintype in _STRUCTURAL_MAINTYPES:
        # Declared on base64 bytes with no boundary and no inner headers,
        # these produce a part a strict parser may reject along with the
        # whole message — so a bad content type would cost the invoice, not
        # just the attachment.
        return _FALLBACK_MIME_TYPE
    return maintype, subtype


def _fit_to_length(filename: str) -> str:
    """Trims a name to ``_MAX_FILENAME_BYTES``, keeping its extension.

    The extension is what a recipient's client keys "open with" off, so
    the stem is what gets shortened; a name truncated to ``invoice-2026``
    opens in nothing. Characters are dropped one at a time rather than
    slicing the encoded bytes, because cutting UTF-8 mid-character
    produces a name no client can decode.
    """
    if len(filename.encode()) <= _MAX_FILENAME_BYTES:
        return filename

    stem, dot, extension = filename.rpartition(".")
    # A "." that far from the end is not an extension, it is part of the
    # name; trimming around it would keep 199 useless bytes and drop the
    # ones that identify the file.
    tail = f"{dot}{extension}" if dot and len(extension.encode()) < _MAX_FILENAME_BYTES else ""
    trimmed = stem if tail else filename
    while trimmed and len(f"{trimmed}{tail}".encode()) > _MAX_FILENAME_BYTES:
        trimmed = trimmed[:-1]
    return f"{trimmed}{tail}"
