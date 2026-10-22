"""Mailbox seam. The demo reads a sample feed. IMAP is used when configured."""

from __future__ import annotations

import email
import imaplib
import os
from email.header import decode_header

from app import db


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _header(raw: str | None) -> str:
    if not raw:
        return ""
    parts = []
    for text, encoding in decode_header(raw):
        if isinstance(text, bytes):
            parts.append(text.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts)


class MockImapMailbox:
    """Stand-in for IMAP UNSEEN. Messages live in the sample mailbox table."""

    name = "mock-imap"

    def fetch_unseen(self) -> list[dict]:
        return db.list_emails(status="new")


class ImapMailbox:
    """Gmail or Outlook over IMAP. Basic auth / app passwords only."""

    name = "imap"

    def __init__(self) -> None:
        self.host = os.environ["IMAP_HOST"]
        self.user = os.environ["IMAP_USER"]
        self.password = os.environ["IMAP_PASSWORD"]
        self.folder = os.environ.get("IMAP_FOLDER", "INBOX")

    def fetch_unseen(self) -> list[dict]:
        client = imaplib.IMAP4_SSL(self.host)
        try:
            client.login(self.user, self.password)
            client.select(self.folder)
            status, data = client.search(None, "UNSEEN")
            if status != "OK" or not data or not data[0]:
                return []
            messages = []
            for number in data[0].split():
                fetched = client.fetch(number, "(RFC822)")
                if fetched[0] != "OK" or not fetched[1]:
                    continue
                payload = fetched[1][0]
                if not isinstance(payload, tuple):
                    continue
                parsed = email.message_from_bytes(payload[1])
                body = _body(parsed)
                sender = email.utils.parseaddr(_header(parsed.get("From")))
                messages.append(
                    {
                        "id": _header(parsed.get("Message-Id")) or f"imap-{number.decode()}",
                        "from_name": sender[0],
                        "from_email": sender[1],
                        "subject": _header(parsed.get("Subject")),
                        "body": body,
                        "received_at": _header(parsed.get("Date")),
                        "status": "new",
                    }
                )
            return messages
        finally:
            try:
                client.logout()
            except Exception:
                pass


def _body(parsed: email.message.Message) -> str:
    if parsed.is_multipart():
        for part in parsed.walk():
            if part.get_content_type() == "text/plain":
                content = part.get_payload(decode=True)
                if isinstance(content, bytes):
                    return content.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    content = parsed.get_payload(decode=True)
    if isinstance(content, bytes):
        return content.decode(parsed.get_content_charset() or "utf-8", errors="replace")
    return _decode(parsed.get_payload())


def mailbox_mode() -> str:
    if os.environ.get("IMAP_HOST", "").strip() and os.environ.get("IMAP_USER", "").strip():
        return "imap"
    return "mock-imap"


def get_mailbox() -> MockImapMailbox | ImapMailbox:
    if mailbox_mode() == "imap":
        return ImapMailbox()
    return MockImapMailbox()
