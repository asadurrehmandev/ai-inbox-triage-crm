"""Normalize a message before any rule looks at it.

Zero-width and bidi controls are stripped first. Off-screen, hidden, white, and
tiny HTML is returned separately so it cannot set a budget. Base64,
quoted-printable, and HTML-entity runs are decoded. A decoded or hidden span
that reads as prose is an instruction channel, whatever the words are.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from quopri import decodestring

_CONFUSABLES = str.maketrans(
    {
        "а": "a", "А": "A", "е": "e", "Е": "E", "о": "o", "О": "O",
        "р": "p", "Р": "P", "с": "c", "С": "C", "у": "y", "У": "Y",
        "х": "x", "Х": "X", "і": "i", "І": "I", "ї": "i", "Ї": "I",
        "ј": "j", "Ј": "J", "ѕ": "s", "Ѕ": "S", "һ": "h", "Һ": "H",
        "ԁ": "d", "Ԁ": "D", "ԛ": "q", "Ԛ": "Q", "ԝ": "w", "Ԝ": "W",
        "В": "B", "К": "K", "М": "M", "Н": "H", "Т": "T",
        "ё": "e", "Ё": "E",
        "α": "a", "Α": "A", "ο": "o", "Ο": "O", "β": "b", "Β": "B",
        "ε": "e", "Ε": "E", "ι": "i", "Ι": "I", "κ": "k", "Κ": "K",
        "μ": "m", "ν": "v", "ρ": "p", "Ρ": "P", "τ": "t", "Τ": "T",
        "υ": "y", "Υ": "Y", "χ": "x", "Χ": "X", "η": "h", "Η": "H",
        "ζ": "z", "Ζ": "Z",
    }
)

# Zero-width, word joiner, BOM, Mongolian vowel separator, and bidi controls.
_INVISIBLE = re.compile("[\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_ZW_INSIDE_WORD = re.compile(r"[0-9A-Za-z][\u180e\u200b\u200c\u200d\u2060\ufeff]+[0-9A-Za-z]")
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069]")

_HIDDEN_COLOR = re.compile(
    r"color\s*:\s*(#fff\b|#ffffff\b|white\b|transparent\b|rgb\(\s*255\s*,\s*255\s*,\s*255\s*\))",
    re.IGNORECASE,
)
_INVISIBLE_CSS = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\.0+)?\b",
    re.IGNORECASE,
)
_FONT_SIZE = re.compile(r"font-size\s*:\s*([0-9.]+)\s*(px|pt|em|rem)?", re.IGNORECASE)
_TEXT_INDENT = re.compile(r"text-indent\s*:\s*-\d{3,}", re.IGNORECASE)
_POSITION = re.compile(r"position\s*:\s*(absolute|fixed)", re.IGNORECASE)
_NEG_OFFSET = re.compile(r"(?:left|top|right|bottom)\s*:\s*-\d{3,}", re.IGNORECASE)
_OVERFLOW_HIDDEN = re.compile(r"overflow\s*:\s*hidden", re.IGNORECASE)
_ZERO_BOX = re.compile(r"(?:width|height)\s*:\s*0(?:px)?\b", re.IGNORECASE)
_ENTITY_RUN = re.compile(r"(?:&#\d{2,6};){4,}|(?:&#x[0-9a-fA-F]{2,4};){4,}")
_QP_RUN = re.compile(r"(?:=[0-9A-Fa-f]{2}){6,}")
_B64 = re.compile(r"(?<![A-Za-z0-9+/])([A-Za-z0-9+/]{40,2000}={0,2})(?![A-Za-z0-9+/])")
_WORDS = re.compile(r"[A-Za-z]{3,}")


@dataclass
class Channels:
    visible: str
    concealed: str
    obfuscated: bool
    concealed_instruction: bool


def fold(value: str) -> str:
    """Strip invisible characters, then NFKC and letters that only look like ASCII."""
    cleaned = _INVISIBLE.sub("", value or "")
    return unicodedata.normalize("NFKC", cleaned).translate(_CONFUSABLES)


def obfuscated_text(value: str) -> bool:
    """A word was split with zero-width characters, or bidi controls are present."""
    raw = value or ""
    return bool(_ZW_INSIDE_WORD.search(raw) or _BIDI.search(raw))


def _tiny_font(style: str) -> bool:
    match = _FONT_SIZE.search(style or "")
    if not match:
        return False
    size = float(match.group(1))
    unit = (match.group(2) or "px").lower()
    if unit == "px":
        return size < 2
    if unit == "pt":
        return size < 2
    return size < 0.15


def style_hides_text(style: str) -> bool:
    if not style:
        return False
    if _HIDDEN_COLOR.search(style) or _INVISIBLE_CSS.search(style) or _tiny_font(style):
        return True
    if _TEXT_INDENT.search(style):
        return True
    if _POSITION.search(style) and _NEG_OFFSET.search(style):
        return True
    if _OVERFLOW_HIDDEN.search(style) and _ZERO_BOX.search(style):
        return True
    return False


def _prose(text: str) -> bool:
    return len(_WORDS.findall(text or "")) >= 4


class _SplitHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.visible: list[str] = []
        self.hidden: list[str] = []
        self._stack: list[bool] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        keys = {key.lower(): (value or "") for key, value in attrs}
        style = keys.get("style", "")
        hide = (
            style_hides_text(style)
            or tag in {"script", "style"}
            or keys.get("aria-hidden", "").lower() == "true"
            or "hidden" in keys
            or keys.get("type", "").lower() == "hidden"
        )
        self._stack.append(hide)
        if hide:
            self._hidden += 1
        if tag in {"br", "p", "div", "tr", "li"} and not self._hidden:
            self.visible.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._stack and self._stack.pop() and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden:
            self.hidden.append(data)
        else:
            self.visible.append(data)

    def handle_comment(self, data: str) -> None:
        self.hidden.append(data)


def split_html(value: str) -> tuple[str, str]:
    """Visible text, and text a person would not see."""
    if not value or "<" not in value or ">" not in value:
        return value or "", ""
    parser = _SplitHtml()
    parser.feed(value)
    parser.close()
    visible = re.sub(r"\n{3,}", "\n\n", "".join(parser.visible)).strip()
    hidden = re.sub(r"\s+", " ", "".join(parser.hidden)).strip()
    return visible, hidden


def _decode_entity_runs(value: str) -> list[str]:
    found: list[str] = []
    for match in _ENTITY_RUN.finditer(value or ""):
        text = unescape(match.group(0)).strip()
        if text:
            found.append(text)
    return found


def _decode_qp_runs(value: str) -> list[str]:
    found: list[str] = []
    for match in _QP_RUN.finditer(value or ""):
        try:
            text = decodestring(match.group(0).encode("ascii")).decode("utf-8")
        except (binascii.Error, UnicodeError, ValueError):
            continue
        text = text.strip()
        if text:
            found.append(text)
    return found


def _maybe_qp_document(value: str) -> str:
    if not value or not re.search(r"=[0-9A-Fa-f]{2}|=\r?\n", value):
        return value or ""
    try:
        return decodestring(value.encode("utf-8")).decode("utf-8")
    except (binascii.Error, UnicodeError, ValueError):
        return value


def _decode_base64(value: str) -> list[str]:
    found: list[str] = []
    for match in _B64.finditer(value or ""):
        blob = match.group(1)
        try:
            raw = base64.b64decode(blob, validate=True)
            text = raw.decode("utf-8")
        except (binascii.Error, UnicodeError, ValueError):
            continue
        text = text.strip()
        if text and not text.startswith("\x00"):
            found.append(text)
    return found


def open_channels(value: str) -> Channels:
    """Visible reading, plus anything recovered from a hidden or encoded channel."""
    raw = value or ""
    obfuscated = obfuscated_text(raw)
    stripped = _INVISIBLE.sub("", raw)
    entity_hits = _decode_entity_runs(stripped)
    # Pull base64 out before quoted-printable. Padding "==" at a line end
    # otherwise looks like a soft line break and the blob is damaged.
    blobs = _decode_base64(stripped)
    without_blobs = _B64.sub(" ", stripped)
    qp_hits = _decode_qp_runs(without_blobs)
    decoded = _maybe_qp_document(unescape(without_blobs))
    visible, hidden = split_html(decoded)
    concealed_bits = [hidden, *entity_hits, *qp_hits, *blobs]
    concealed = "\n".join(bit.strip() for bit in concealed_bits if bit and bit.strip())
    instruction = any(_prose(bit) for bit in concealed_bits)
    return Channels(
        visible=fold(visible).strip(),
        concealed=fold(concealed).strip(),
        obfuscated=obfuscated,
        concealed_instruction=instruction,
    )
