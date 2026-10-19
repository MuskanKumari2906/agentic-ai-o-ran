"""Apply structured fixes {parameter: new_value} to a config file as minimal line edits."""
from __future__ import annotations

import difflib
import re

from .security import PARAM_PATHS, security_view


def _fmt(v) -> str:
    if isinstance(v, list):
        return "( " + ", ".join(f'"{x}"' for x in v) + " )"
    return f'"{v}"'


def apply_fixes(text: str, fixes: dict) -> tuple[str, list[str]]:
    """Return (new_text, errors). Each fix replaces the value on the parameter's own line."""
    sec = security_view(text)
    lines = text.split("\n")
    errors = []
    for p, v in fixes.items():
        if p not in PARAM_PATHS:
            errors.append(f"unknown parameter {p}")
            continue
        ln = sec.lines.get(p)
        if ln is None:
            errors.append(f"parameter {p} not found")
            continue
        name = PARAM_PATHS[p].split(".")[-1]
        old = lines[ln - 1]
        new, n = re.subn(rf"({re.escape(name)}\s*=\s*)(\([^)]*\)|\"[^\"]*\"|[^;#\s]+)",
                         lambda m: m.group(1) + _fmt(v), old, count=1)
        if n == 0:
            errors.append(f"could not rewrite line {ln} for {p}")
            continue
        lines[ln - 1] = new
    return "\n".join(lines), errors


def changed_lines(a: str, b: str) -> list[int]:
    out = []
    sm = difflib.SequenceMatcher(a=a.split("\n"), b=b.split("\n"), autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            out.extend(range(i1 + 1, max(i2, i1 + 1) + 1))
    return sorted(set(out))


def unified_diff(a: str, b: str, name="gnb.conf") -> str:
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True),
                                        fromfile=f"a/{name}", tofile=f"b/{name}", n=1))
