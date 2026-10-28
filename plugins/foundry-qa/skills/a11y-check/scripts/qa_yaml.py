"""qa_yaml: a tiny, dependency-free parser for the YAML subset foundry-qa uses.

Journey files, persona frontmatter and stories can be written in this subset,
so students do not need `pip install pyyaml`. Anything this parser accepts is
also valid YAML 1.2, so the same file works with real YAML tools.

Supported:
  - block mappings      key: value
  - block sequences     - item          (items may be scalars or mappings)
  - flow mappings       {selector: "#email", value: "a@b.co"}
  - flow sequences      [desktop-1440x900, phone-390x844]
  - scalars             plain, 'single quoted', "double quoted" (\\n \\t \\" \\\\)
  - true / false / null / ~ / integers / floats
  - comments            # to end of line (only after whitespace or at line start)

Not supported (raises YamlError with the line number):
  - block scalars (| and >), anchors (&a, *a), tags (!!str), multi-document (---
    is allowed only as the very first line), tabs for indentation.

Gotchas that match real YAML, so quote these values:
  - a selector that starts with # (a comment otherwise), [ or { (a flow
    collection otherwise), or contains ": " or " #".
  - yes/no/on/off stay STRINGS here (YAML 1.2 core schema). Use true/false.

Also accepts JSON: `load_text` tries JSON first when the text starts with { or [.
"""
from __future__ import annotations

import json
import re
from typing import Any

__all__ = ["YamlError", "loads", "load_text", "load_file"]


class YamlError(ValueError):
    """A parse error, with a 1-based line number when one is known."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


_INT = re.compile(r"^[-+]?\d+$")
_FLOAT = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")


def _strip_comment(text: str) -> str:
    """Remove a trailing comment, respecting quotes."""
    out = []
    quote = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            out.append(ch)
            if quote == '"' and ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                quote = None
        else:
            if ch == "#" and (i == 0 or text[i - 1] in " \t"):
                break
            if ch in "'\"" and (i == 0 or text[i - 1] in " \t:-[{,"):
                quote = ch
            out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _prepare(text: str) -> list[tuple[int, str, int]]:
    lines = []
    raw_lines = text.splitlines()
    for idx, raw in enumerate(raw_lines, start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError("tabs are not allowed for indentation", idx)
        body = _strip_comment(raw)
        if not body.strip():
            continue
        if body.strip() == "---":
            if lines:
                raise YamlError("multiple documents are not supported", idx)
            continue
        indent = len(body) - len(body.lstrip(" "))
        lines.append((indent, body.strip(), idx))
    return lines


def _unquote_double(s: str, line: int) -> str:
    out = []
    i = 0
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "r": "\r", "0": "\0"}
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            if i + 1 >= len(s):
                raise YamlError("dangling backslash in double-quoted string", line)
            nxt = s[i + 1]
            if nxt not in escapes:
                raise YamlError(f"unsupported escape \\{nxt}", line)
            out.append(escapes[nxt])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _scalar(token: str, line: int) -> Any:
    t = token.strip()
    if t == "":
        return None
    if t[0] == '"':
        if len(t) < 2 or t[-1] != '"':
            raise YamlError(f"unterminated double-quoted string: {t}", line)
        return _unquote_double(t[1:-1], line)
    if t[0] == "'":
        if len(t) < 2 or t[-1] != "'":
            raise YamlError(f"unterminated single-quoted string: {t}", line)
        return t[1:-1].replace("''", "'")
    if t[0] in "&*!|>":
        raise YamlError(f"unsupported YAML feature ({t[0]}); quote the value if it is a string", line)
    if t in ("null", "~", "Null", "NULL"):
        return None
    if t in ("true", "True", "TRUE"):
        return True
    if t in ("false", "False", "FALSE"):
        return False
    if _INT.match(t):
        return int(t)
    if _FLOAT.match(t):
        return float(t)
    return t


# ── flow collections ──────────────────────────────────────────────────────────

def _parse_flow(text: str, line: int) -> Any:
    value, pos = _flow_value(text, 0, line)
    pos = _skip_ws(text, pos)
    if pos != len(text):
        raise YamlError(f"unexpected trailing text after flow collection: {text[pos:]!r}", line)
    return value


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    return pos


def _flow_value(text: str, pos: int, line: int) -> tuple[Any, int]:
    pos = _skip_ws(text, pos)
    if pos >= len(text):
        raise YamlError("unexpected end of flow collection", line)
    ch = text[pos]
    if ch == "{":
        return _flow_map(text, pos + 1, line)
    if ch == "[":
        return _flow_seq(text, pos + 1, line)
    return _flow_scalar(text, pos, line, stops=",]}")


def _flow_scalar(text: str, pos: int, line: int, stops: str) -> tuple[Any, int]:
    pos = _skip_ws(text, pos)
    if pos < len(text) and text[pos] in "'\"":
        q = text[pos]
        i = pos + 1
        while i < len(text):
            if q == '"' and text[i] == "\\":
                i += 2
                continue
            if text[i] == q:
                if q == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                return _scalar(text[pos : i + 1], line), i + 1
            i += 1
        raise YamlError("unterminated quoted string in flow collection", line)
    i = pos
    while i < len(text) and text[i] not in stops:
        if ":" in stops and text[i] == ":" and (i + 1 == len(text) or text[i + 1] in " ,]}"):
            break
        i += 1
    return _scalar(text[pos:i], line), i


def _flow_seq(text: str, pos: int, line: int) -> tuple[list, int]:
    items: list = []
    pos = _skip_ws(text, pos)
    if pos < len(text) and text[pos] == "]":
        return items, pos + 1
    while True:
        value, pos = _flow_value(text, pos, line)
        items.append(value)
        pos = _skip_ws(text, pos)
        if pos >= len(text):
            raise YamlError("unterminated flow sequence (missing ])", line)
        if text[pos] == ",":
            pos += 1
            continue
        if text[pos] == "]":
            return items, pos + 1
        raise YamlError(f"expected , or ] in flow sequence, got {text[pos]!r}", line)


def _flow_map(text: str, pos: int, line: int) -> tuple[dict, int]:
    out: dict = {}
    pos = _skip_ws(text, pos)
    if pos < len(text) and text[pos] == "}":
        return out, pos + 1
    while True:
        key, pos = _flow_scalar(text, pos, line, stops=":,}")
        pos = _skip_ws(text, pos)
        if pos >= len(text) or text[pos] != ":":
            raise YamlError(f"expected ':' after key {key!r} in flow mapping", line)
        pos += 1
        pos = _skip_ws(text, pos)
        if pos < len(text) and text[pos] in ",}":
            value = None
        else:
            value, pos = _flow_value(text, pos, line)
        if not isinstance(key, str):
            key = str(key)
        out[key] = value
        pos = _skip_ws(text, pos)
        if pos >= len(text):
            raise YamlError("unterminated flow mapping (missing })", line)
        if text[pos] == ",":
            pos += 1
            continue
        if text[pos] == "}":
            return out, pos + 1
        raise YamlError(f"expected , or }} in flow mapping, got {text[pos]!r}", line)


def _value(token: str, line: int) -> Any:
    t = token.strip()
    if t.startswith("{") or t.startswith("["):
        return _parse_flow(t, line)
    return _scalar(t, line)


# ── block structure ───────────────────────────────────────────────────────────

def _split_key(text: str, line: int) -> tuple[str, str] | None:
    """Split 'key: value' at the first ': ' outside quotes. None if not a mapping line."""
    if text[0] in "'\"":
        q = text[0]
        end = text.find(q, 1)
        if end == -1:
            raise YamlError("unterminated quoted key", line)
        rest = text[end + 1 :]
        if rest == ":" or rest.startswith(": "):
            return str(_scalar(text[: end + 1], line)), rest[1:].strip()
        return None
    if text[0] in "[{":
        return None
    m = re.match(r"^([^:]+?):(?:\s+(.*))?$", text)
    if not m:
        return None
    return m.group(1).strip(), (m.group(2) or "").strip()


class _Parser:
    def __init__(self, lines: list[tuple[int, str, int]]):
        self.lines = lines

    def block(self, i: int, indent: int) -> tuple[Any, int]:
        ind, text, ln = self.lines[i]
        if ind != indent:
            raise YamlError("bad indentation", ln)
        if text == "-" or text.startswith("- "):
            return self.seq(i, indent)
        return self.mapping(i, indent)

    def seq(self, i: int, indent: int) -> tuple[list, int]:
        items: list = []
        while i < len(self.lines):
            ind, text, ln = self.lines[i]
            if ind < indent:
                break
            if ind > indent:
                raise YamlError("bad indentation inside sequence", ln)
            if not (text == "-" or text.startswith("- ")):
                break
            rest = text[1:].strip()
            if rest == "":
                if i + 1 < len(self.lines) and self.lines[i + 1][0] > indent:
                    value, i = self.block(i + 1, self.lines[i + 1][0])
                else:
                    value, i = None, i + 1
                items.append(value)
                continue
            kv = _split_key(rest, ln)
            if kv is not None and not rest.startswith(("{", "[")):
                child_indent = indent + (len(text) - len(rest))
                self.lines[i] = (child_indent, rest, ln)
                value, i = self.mapping(i, child_indent)
                items.append(value)
                continue
            items.append(_value(rest, ln))
            i += 1
        return items, i

    def mapping(self, i: int, indent: int) -> tuple[dict, int]:
        out: dict = {}
        while i < len(self.lines):
            ind, text, ln = self.lines[i]
            if ind < indent:
                break
            if ind > indent:
                raise YamlError("bad indentation inside mapping", ln)
            if text == "-" or text.startswith("- "):
                break
            kv = _split_key(text, ln)
            if kv is None:
                raise YamlError(f"expected 'key: value', got {text!r}", ln)
            key, rest = kv
            if key in out:
                raise YamlError(f"duplicate key {key!r}", ln)
            if rest in ("|", ">", "|-", ">-", "|+", ">+"):
                raise YamlError("block scalars (| and >) are not supported; use a quoted string", ln)
            if rest == "":
                if i + 1 < len(self.lines):
                    nind, ntext, _ = self.lines[i + 1]
                    if nind > indent:
                        out[key], i = self.block(i + 1, nind)
                        continue
                    if nind == indent and (ntext == "-" or ntext.startswith("- ")):
                        out[key], i = self.seq(i + 1, indent)
                        continue
                out[key] = None
                i += 1
                continue
            out[key] = _value(rest, ln)
            i += 1
        return out, i


def loads(text: str) -> Any:
    """Parse the supported YAML subset. Returns None for an empty document."""
    lines = _prepare(text)
    if not lines:
        return None
    p = _Parser(lines)
    first_indent = lines[0][0]
    ind, text0, ln = lines[0]
    if len(lines) == 1 and _split_key(text0, ln) is None and not text0.startswith("- ") and text0 != "-":
        return _value(text0, ln)
    value, i = p.block(0, first_indent)
    if i != len(lines):
        raise YamlError("unexpected content (check indentation)", lines[i][2])
    return value


def load_text(text: str) -> Any:
    """JSON if it looks like JSON, otherwise the YAML subset."""
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass  # might be a YAML flow collection; fall through
    return loads(text)


def load_file(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if str(path).endswith(".json"):
        return json.loads(text)
    return load_text(text)
