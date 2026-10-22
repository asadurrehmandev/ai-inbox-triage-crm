"""Mailbox seam. The demo reads a sample feed. IMAP is used when configured."""

from __future__ import annotations

import codecs
import email
import email.utils
import imaplib
import logging
import os
import re
from datetime import timezone
from email.header import decode_header

from app.prepare import html_to_text

logger = logging.getLogger("lane.mailbox")
FETCH_CAP = 200


def _header(raw: str | None) -> str:
    if not raw:
        return ""
    parts = []
    for text, encoding in decode_header(raw):
        if isinstance(text, bytes):
            parts.append(decode_bytes(text, encoding))
        else:
            parts.append(text)
    return "".join(parts)


def decode_bytes(raw: bytes, charset: str | None) -> str:
    name = (charset or "utf-8").strip() or "utf-8"
    try:
        codecs.lookup(name)
    except LookupError:
        logger.warning("imap_unknown_charset %s", name)
        name = "utf-8"
    return raw.decode(name, errors="replace")


def normalize_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return ""
    if parsed is None:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def message_body(parsed: email.message.Message) -> str:
    plain = ""
    html = ""
    parts = parsed.walk() if parsed.is_multipart() else [parsed]
    for part in parts:
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        text = decode_bytes(payload, part.get_content_charset())
        kind = part.get_content_type()
        if kind == "text/plain" and not plain:
            plain = text
        elif kind == "text/html" and not html:
            html = text
    if plain.strip():
        return plain
    if html.strip():
        return html_to_text(html)
    return ""


def parse_message(raw: bytes, uid: str, uidvalidity: str) -> dict:
    parsed = email.message_from_bytes(raw)
    sender = email.utils.parseaddr(_header(parsed.get("From")))
    message_id = _header(parsed.get("Message-Id")).strip().strip("<>")
    if not message_id:
        message_id = f"imap-{uidvalidity}-{uid}"
    def _all(name: str) -> list[str]:
        return [_header(item) for item in (parsed.get_all(name) or []) if item]

    auth = _all("Authentication-Results")
    arc = _all("ARC-Authentication-Results")
    received_spf = _all("Received-SPF")
    headers: dict[str, str | list[str]] = {}
    if auth:
        headers["Authentication-Results"] = auth if len(auth) > 1 else auth[0]
    if arc:
        headers["ARC-Authentication-Results"] = arc if len(arc) > 1 else arc[0]
    if received_spf:
        headers["Received-SPF"] = received_spf if len(received_spf) > 1 else received_spf[0]
    return {
        "id": message_id,
        "message_id": message_id,
        "from_name": sender[0],
        "from_email": sender[1],
        "subject": _header(parsed.get("Subject")),
        "body": message_body(parsed),
        "received_at": normalize_date(_header(parsed.get("Date"))),
        "auto_submitted": _header(parsed.get("Auto-Submitted")),
        "in_reply_to": _header(parsed.get("In-Reply-To")),
        "references": _header(parsed.get("References")),
        "headers": headers,
        "imap_uid": uid,
        "status": "new",
    }


def _uidvalidity(client, folder: str) -> str:
    try:
        status, data = client.status(folder, "(UIDVALIDITY)")
    except Exception:
        logger.warning("imap_uidvalidity_failed", exc_info=True)
        return "0"
    if status != "OK" or not data:
        return "0"
    blob = data[0].decode(errors="replace") if isinstance(data[0], bytes) else str(data[0])
    found = re.search(r"UIDVALIDITY\s+(\d+)", blob, re.IGNORECASE)
    return found.group(1) if found else "0"


def _payload_bytes(fetched) -> bytes | None:
    if not fetched or fetched[0] != "OK" or not fetched[1]:
        return None
    for item in fetched[1]:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def read_unseen(client, folder: str = "INBOX", limit: int = FETCH_CAP) -> list[dict]:
    """Parse UNSEEN mail without marking it seen. One bad message does not stop the pass."""
    client.select(folder)
    status, data = client.uid("SEARCH", None, "UNSEEN")
    if status != "OK" or not data or not data[0]:
        return []
    uids = data[0].split()[:limit]
    validity = _uidvalidity(client, folder)
    messages = []
    for uid in uids:
        token = uid.decode() if isinstance(uid, bytes) else str(uid)
        try:
            fetched = client.uid("FETCH", token, "(BODY.PEEK[])")
            raw = _payload_bytes(fetched)
            if raw is None:
                logger.warning("imap_empty_fetch uid=%s", token)
                continue
            messages.append(parse_message(raw, token, validity))
        except Exception:
            logger.warning("imap_skip uid=%s", token, exc_info=True)
    return messages


def mark_seen(client, uid: str) -> None:
    client.uid("STORE", uid, "+FLAGS", "\\Seen")


class MockImapMailbox:
    """Stand-in for IMAP UNSEEN. Messages live in the sample mailbox table."""

    name = "mock-imap"

    def fetch_unseen(self) -> list[dict]:
        from app import db

        return db.list_emails(status="new")

    def mark_seen(self, uid: str | None) -> None:
        return None


class ImapMailbox:
    """Gmail or Outlook over IMAP. Basic auth, with a socket timeout."""

    name = "imap"

    def __init__(self) -> None:
        self.host = os.environ["IMAP_HOST"]
        self.user = os.environ["IMAP_USER"]
        self.password = os.environ["IMAP_PASSWORD"]
        self.folder = os.environ.get("IMAP_FOLDER", "INBOX")
        self._client: imaplib.IMAP4_SSL | None = None

    def _open(self) -> imaplib.IMAP4_SSL:
        if self._client is None:
            self._client = imaplib.IMAP4_SSL(self.host, timeout=30)
            self._client.login(self.user, self.password)
        return self._client

    def fetch_unseen(self) -> list[dict]:
        try:
            return read_unseen(self._open(), self.folder, FETCH_CAP)
        finally:
            self.close()

    def mark_seen(self, uid: str | None) -> None:
        if not uid:
            return
        try:
            client = self._open()
            client.select(self.folder)
            mark_seen(client, uid)
        except Exception:
            logger.warning("imap_mark_seen_failed uid=%s", uid, exc_info=True)
        finally:
            self.close()

    def close(self) -> None:
        if self._client is None:
            return
        try:
            self._client.logout()
        except Exception:
            pass
        self._client = None


def mailbox_mode() -> str:
    if os.environ.get("IMAP_HOST", "").strip() and os.environ.get("IMAP_USER", "").strip():
        return "imap"
    return "mock-imap"


def get_mailbox() -> MockImapMailbox | ImapMailbox:
    if mailbox_mode() == "imap":
        return ImapMailbox()
    return MockImapMailbox()
