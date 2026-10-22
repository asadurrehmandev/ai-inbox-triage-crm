"""Normalize a message before any rule looks at it.

NFKC folds compatibility characters. A small confusable map folds letters that
look like ASCII but are not. Hidden HTML is returned separately so a budget
or an instruction painted white is not treated as the visible message.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

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

_HIDDEN_COLOR = re.compile(
    r"color\s*:\s*(#fff\b|#ffffff\b|white\b|rgb\(\s*255\s*,\s*255\s*,\s*255\s*\))",
    re.IGNORECASE,
)
_TINY = re.compile(r"font-size\s*:\s*(0|1px|0px|0\.?0*px)", re.IGNORECASE)
_INVISIBLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\.0+)?\b", re.IGNORECASE)


def fold(value: str) -> str:
    """NFKC, then letters that only look like ASCII."""
    return unicodedata.normalize("NFKC", value or "").translate(_CONFUSABLES)


def style_hides_text(style: str) -> bool:
    if not style:
        return False
    return bool(_HIDDEN_COLOR.search(style) or _TINY.search(style) or _INVISIBLE.search(style))


class _SplitHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.visible: list[str] = []
        self.hidden: list[str] = []
        self._stack: list[bool] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        style = ""
        for key, value in attrs:
            if key.lower() == "style":
                style = value or ""
        hide = style_hides_text(style) or tag in {"script", "style"}
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
    """Visible text, and text a person would not see (comments, white, 1px)."""
    if not value or "<" not in value or ">" not in value:
        return value or "", ""
    parser = _SplitHtml()
    parser.feed(value)
    parser.close()
    visible = re.sub(r"\n{3,}", "\n\n", "".join(parser.visible)).strip()
    hidden = re.sub(r"\s+", " ", "".join(parser.hidden)).strip()
    return visible, hidden
