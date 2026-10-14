"""Tiny HTML tag-balance checker shared by page-generator tests."""

from __future__ import annotations

import html.parser

VOID = {"meta", "link", "br", "img", "input", "hr", "source", "col", "area", "base", "wbr"}


class _Balance(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):  # noqa: ANN001
        pass  # <meta ... /> style: opens and closes itself

    def handle_endtag(self, tag):  # noqa: ANN001
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> with open {self.stack[-3:]}")
            return
        self.stack.pop()


def check_balanced(text: str) -> None:
    p = _Balance()
    p.feed(text)
    p.close()
    assert not p.errors, p.errors[:3]
    assert p.stack == [], p.stack
