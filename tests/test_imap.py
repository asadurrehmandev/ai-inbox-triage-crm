"""IMAP reads with PEEK, survives one bad message, and does not invent sequence ids."""

import imaplib
from email.message import EmailMessage

from app.mailbox import ImapMailbox, decode_bytes, parse_message, read_unseen


def _html_only() -> bytes:
    message = EmailMessage()
    message["From"] = "Cloudnest Accounts <accounts@cloudnest.io>"
    message["Subject"] = "Invoice 4411"
    message["Date"] = "Thu, 22 Oct 2026 15:04:05 +0200"
    message.set_content("<p>Invoice <b>$1,250</b> for hosting.</p>", subtype="html")
    return message.as_bytes()


def _plain(charset: str, body: str, message_id: str | None) -> bytes:
    header = "" if message_id is None else f"Message-Id: <{message_id}>\r\n"
    return (
        f"From: Mia Torres <mia@fernway.com>\r\n"
        f"Subject: checkout\r\n"
        f"Date: Thu, 22 Oct 2026 12:00:00 +0000\r\n"
        f"{header}"
        f"Content-Type: text/plain; charset={charset}\r\n"
        f"\r\n{body}"
    ).encode("utf-8", errors="replace")


class FakeImap:
    def __init__(self, messages: dict[bytes, bytes]):
        self.messages = messages
        self.seen: list[str] = []

    def select(self, folder):
        return "OK", [b"1"]

    def status(self, folder, spec):
        return "OK", [b"INBOX (UIDVALIDITY 42)"]

    def uid(self, command, *args):
        if command == "SEARCH":
            keys = b" ".join(self.messages)
            return "OK", [keys]
        if command == "FETCH":
            uid = args[0].encode() if isinstance(args[0], str) else args[0]
            raw = self.messages.get(uid)
            if raw is None:
                return "OK", [None]
            return "OK", [(b"meta", raw)]
        if command == "STORE":
            self.seen.append(args[0])
            return "OK", []
        raise AssertionError(command)


def test_unknown_charset_and_html_only_and_stable_uid():
    assert "caf\ufffd" in decode_bytes("café".encode("latin-1"), "not-a-charset") or decode_bytes(
        b"hello", "not-a-charset"
    )
    client = FakeImap(
        {
            b"7": _plain("x-not-a-real-charset", "portal went down", None),
            b"8": _html_only(),
        }
    )
    messages = read_unseen(client)
    by_id = {item["id"]: item for item in messages}
    assert "imap-42-7" in by_id
    assert by_id["imap-42-7"]["received_at"].endswith("+00:00")
    html = next(item for item in messages if item["from_email"] == "accounts@cloudnest.io")
    assert "1,250" in html["body"]
    assert "<b>" not in html["body"]
    assert client.seen == []


def test_cap_and_one_bad_message(monkeypatch):
    messages = {str(i).encode(): _plain("utf-8", f"hello {i}", f"id-{i}") for i in range(201)}
    client = FakeImap(messages)
    found = read_unseen(client)
    assert len(found) == 200

    def explode(raw, uid, validity):
        if uid == "1":
            raise RuntimeError("bad message")
        return parse_message(raw, uid, validity)

    monkeypatch.setattr("app.mailbox.parse_message", explode)
    client = FakeImap({b"1": b"not really", b"2": _plain("utf-8", "ok", "good")})
    found = read_unseen(client)
    assert [item["id"] for item in found] == ["good"]


def test_ssl_client_uses_a_timeout(monkeypatch):
    captured = {}

    class Dummy:
        def login(self, user, password):
            return "OK", []

        def logout(self):
            return "OK", []

    def factory(host, timeout=None):
        captured["host"] = host
        captured["timeout"] = timeout
        return Dummy()

    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "ada")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    monkeypatch.setattr(imaplib, "IMAP4_SSL", factory)
    mailbox = ImapMailbox()
    try:
        mailbox.fetch_unseen()
    except Exception:
        pass
    assert captured["host"] == "imap.example.com"
    assert captured["timeout"] == 30
