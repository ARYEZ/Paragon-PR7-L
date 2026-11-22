"""Mp3tag's filter (View > Filter, F3): which files the list shows. (No Qt here.)

    beatles abbey                       plain words: each must appear in some field or the file name
    artist HAS beatles                  the field contains it (any case)        title IS "Come Together"
    %year% LESS 1990                    numbers: GREATER, LESS, EQUAL           genre MATCHES ^(rock|pop)$
    comment PRESENT    album MISSING    the field has a value / has none        "$len(%title%)" GREATER 40
    ... AND ...   ... OR ...   NOT ...   ( ... )                                 %_covers% MISSING

Operators are written in capitals, as in Mp3tag. A field can be written as title or %title%; anything in
quotes is a format string ("%artist% - %title%" HAS live).
"""

from __future__ import annotations

import re

from . import script

OPERATORS = {"HAS", "IS", "MATCHES", "PRESENT", "MISSING", "GREATER", "LESS", "EQUAL"}
NO_VALUE = {"PRESENT", "MISSING"}
KEYWORDS = OPERATORS | {"AND", "OR", "NOT"}


class FilterError(Exception):
    pass


def _tokens(text: str) -> list[tuple[str, str]]:
    """(kind, text): 'q' quoted, '(' ')', 'w' word."""
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            out.append((c, c))
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while True:
                k = text.find('"', j)
                if k < 0:
                    raise FilterError("A quote \" isn't closed.")
                if text[k + 1:k + 2] == '"':  # "" inside quotes is one "
                    buf.append(text[j:k + 1])
                    j = k + 2
                    continue
                buf.append(text[j:k])
                i = k + 1
                break
            out.append(("q", "".join(buf)))
        else:  # a word; brackets opened inside it belong to it: ^(rock|pop)$ is one word
            j, depth = i, 0
            while j < len(text) and not text[j].isspace() and text[j] != '"':
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    if depth == 0:
                        break  # closes a group opened before this word
                    depth -= 1
                j += 1
            out.append(("w", text[i:j]))
            i = j
    return out


def _number(text: str) -> float | None:
    m = re.match(r"\s*(-?\d+(?:[.,]\d+)?)", text)
    return float(m.group(1).replace(",", ".")) if m else None


def _operand(kind: str, text: str) -> str:
    """A bare field name becomes %name%; a quoted text or anything with % or $ is a format string."""
    if kind == "q" or "%" in text or "$" in text:
        return text
    return f"%{text}%"


def _value(ctx: script.Context, fmt: str) -> str:
    return script.format_string(fmt, ctx)


class _Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def word(self, w: str) -> bool:
        kind, text = self.peek()
        return kind == "w" and text == w

    def expr(self):
        left = self.and_()
        while self.word("OR"):
            self.take()
            right = self.and_()
            left = (lambda a, b: lambda ctx: a(ctx) or b(ctx))(left, right)
        return left

    def and_(self):
        left = self.not_()
        while self.word("AND"):
            self.take()
            right = self.not_()
            left = (lambda a, b: lambda ctx: a(ctx) and b(ctx))(left, right)
        return left

    def not_(self):
        if self.word("NOT"):
            self.take()
            inner = self.not_()
            return lambda ctx: not inner(ctx)
        return self.primary()

    def primary(self):
        kind, text = self.peek()
        if kind == "(":
            self.take()
            inner = self.expr()
            if self.take()[0] != ")":
                raise FilterError("A ( isn't closed with ).")
            return inner
        if kind not in ("w", "q") or (kind == "w" and text in KEYWORDS):
            raise FilterError(f"A field was expected{' before ' + text if text else ' at the end'}.")
        self.take()
        left = _operand(kind, text)
        op_kind, op = self.take()
        if op_kind != "w" or op not in OPERATORS:
            raise FilterError(f"After {text}: HAS, IS, MATCHES, PRESENT, MISSING, GREATER, LESS or EQUAL.")
        if op in NO_VALUE:
            want = op == "PRESENT"
            return lambda ctx: bool(_value(ctx, left)) == want
        vkind, value = self.take()
        if vkind not in ("w", "q"):
            raise FilterError(f"{op} needs a value after it.")
        if op == "HAS":
            low = value.lower()
            return lambda ctx: low in _value(ctx, left).lower()
        if op == "IS":
            low = value.lower()
            return lambda ctx: _value(ctx, left).lower() == low
        if op == "MATCHES":
            try:
                rx = re.compile(value, re.I)
            except re.error as e:
                raise FilterError(f"MATCHES {value}: {e}") from e
            return lambda ctx: bool(rx.search(_value(ctx, left)))
        n = _number(value)
        if n is None:
            raise FilterError(f"{op} needs a number, not {value}.")

        def compare(ctx, op=op, n=n):
            v = _number(_value(ctx, left))
            if v is None:
                return False
            return v > n if op == "GREATER" else v < n if op == "LESS" else v == n
        return compare


def compile_filter(text: str):
    """A function TagFile -> bool, or None for an empty filter (show everything)."""
    text = text.strip()
    if not text:
        return None
    toks = _tokens(text)
    if not any(k == "w" and t in KEYWORDS for k, t in toks):
        words = [t.lower() for _, t in toks if t not in "()"]
        return lambda tf: _plain(tf, words)
    p = _Parser(toks)
    pred = p.expr()
    if p.i < len(toks):
        raise FilterError(f"Not understood from here: {' '.join(t for _, t in toks[p.i:])}")
    return lambda tf: pred(script.Context(tf))


def _plain(tf, words: list[str]) -> bool:
    hay = " ".join([tf.filename] + [v for values in tf.fields.values() for v in values]).lower()
    return all(w in hay for w in words)
