"""Small libconfig parser used for OAI-style gNB configuration files.

OAI's nr-softmodem reads libconfig syntax. We only need enough of the grammar to
(1) decide whether a file is syntactically valid (verifier check C5), and
(2) find every setting together with its dotted path, value and line number
(verifier check C2, the twin, the dataset labeller).

Grammar subset: groups `{}`, lists `()`, arrays `[]`, scalars (string, int,
float, bool), `=` or `:` assignment, `;`/`,` terminators, `#`, `//`, `/* */`
comments. Adjacent string literals are concatenated as libconfig does.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>[ \t\r]+)
  | (?P<nl>\n)
  | (?P<comment>\#[^\n]*|//[^\n]*)
  | (?P<mcomment>/\*.*?\*/)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<float>[-+]?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?|[-+]?\d+[eE][-+]?\d+)
  | (?P<hex>0[xX][0-9a-fA-F]+L{0,2})
  | (?P<int>[-+]?\d+L{0,2})
  | (?P<bool>(?i:true|false)\b)
  | (?P<name>[A-Za-z\*][-A-Za-z0-9_\*]*)
  | (?P<punct>[{}()\[\]=:;,])
    """,
    re.VERBOSE | re.DOTALL,
)


class ConfigSyntaxError(ValueError):
    def __init__(self, msg: str, line: int):
        super().__init__(f"line {line}: {msg}")
        self.line = line


@dataclass
class Tok:
    kind: str
    value: str
    line: int


@dataclass
class Setting:
    path: str          # dotted path, list indices as [i]
    value: Any
    line: int


@dataclass
class ParsedConfig:
    root: dict
    settings: list[Setting] = field(default_factory=list)

    def get(self, path: str, default=None):
        for s in self.settings:
            if s.path == path:
                return s.value
        return default

    def find(self, path: str) -> Setting | None:
        for s in self.settings:
            if s.path == path:
                return s
        return None


def tokenize(text: str) -> list[Tok]:
    toks: list[Tok] = []
    line = 1
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise ConfigSyntaxError(f"unexpected character {text[pos]!r}", line)
        kind = m.lastgroup
        val = m.group(kind)
        if kind == "nl":
            line += 1
        elif kind == "mcomment":
            line += val.count("\n")
        elif kind not in ("ws", "comment"):
            toks.append(Tok(kind, val, line))
        pos = m.end()
    return toks


class _Parser:
    def __init__(self, toks: list[Tok]):
        self.toks = toks
        self.i = 0
        self.settings: list[Setting] = []

    def peek(self) -> Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self, kind=None, value=None) -> Tok:
        t = self.peek()
        if t is None:
            last = self.toks[-1].line if self.toks else 1
            raise ConfigSyntaxError("unexpected end of file", last)
        if (kind and t.kind != kind) or (value and t.value != value):
            raise ConfigSyntaxError(f"expected {value or kind}, got {t.value!r}", t.line)
        self.i += 1
        return t

    def parse_settings(self, prefix: str, closing: str | None) -> dict:
        out: dict = {}
        while True:
            t = self.peek()
            if t is None:
                if closing:
                    raise ConfigSyntaxError(f"missing '{closing}'", self.toks[-1].line)
                return out
            if closing and t.kind == "punct" and t.value == closing:
                return out
            name = self.take("name")
            nxt = self.take("punct")
            if nxt.value not in ("=", ":"):
                raise ConfigSyntaxError(f"expected '=' after {name.value}", nxt.line)
            path = f"{prefix}.{name.value}" if prefix else name.value
            out[name.value] = self.parse_value(path, name.line)
            t = self.peek()
            if t is not None and t.kind == "punct" and t.value in (";", ","):
                self.i += 1

    def parse_value(self, path: str, line: int):
        t = self.peek()
        if t is None:
            raise ConfigSyntaxError("missing value", line)
        if t.kind == "punct" and t.value == "{":
            self.i += 1
            val = self.parse_settings(path, "}")
            self.take("punct", "}")
            self.settings.append(Setting(path, "<group>", line))
            return val
        if t.kind == "punct" and t.value in ("(", "["):
            close = ")" if t.value == "(" else "]"
            self.i += 1
            items = []
            idx = 0
            while True:
                p = self.peek()
                if p is None:
                    raise ConfigSyntaxError(f"missing '{close}'", t.line)
                if p.kind == "punct" and p.value == close:
                    self.i += 1
                    break
                items.append(self.parse_value(f"{path}[{idx}]", p.line))
                idx += 1
                p = self.peek()
                if p is not None and p.kind == "punct" and p.value == ",":
                    self.i += 1
            if all(not isinstance(x, (dict, list)) for x in items):
                self.settings.append(Setting(path, items, line))
            else:
                self.settings.append(Setting(path, "<list>", line))
            return items
        return self.parse_scalar(path, line)

    def parse_scalar(self, path: str, line: int):
        t = self.take()
        if t.kind == "string":
            s = _unquote(t.value)
            while (p := self.peek()) is not None and p.kind == "string":
                s += _unquote(p.value)
                self.i += 1
            val: Any = s
        elif t.kind == "int":
            val = int(t.value.rstrip("L"))
        elif t.kind == "hex":
            val = int(t.value.rstrip("L"), 16)
        elif t.kind == "float":
            val = float(t.value)
        elif t.kind == "bool":
            val = t.value.lower() == "true"
        else:
            raise ConfigSyntaxError(f"unexpected token {t.value!r}", t.line)
        self.settings.append(Setting(path, val, t.line))
        return val


def _unquote(s: str) -> str:
    return bytes(s[1:-1], "utf-8").decode("unicode_escape") if "\\" in s else s[1:-1]


def parse(text: str) -> ParsedConfig:
    p = _Parser(tokenize(text))
    root = p.parse_settings("", None)
    return ParsedConfig(root=root, settings=p.settings)


def is_valid(text: str) -> tuple[bool, str | None]:
    try:
        parse(text)
        return True, None
    except ConfigSyntaxError as e:
        return False, str(e)
