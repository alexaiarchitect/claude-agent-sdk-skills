"""A small frontmatter reader for `prompt.md` and `graders/*.md`.

Case and grader files carry a `---` delimited header. The plugin reads it
without a YAML dependency (the plugin is stdlib-only and the runner copy in a
user's project should not need one either), so the accepted grammar is a
deliberate subset of YAML, and both sides share this exact module: the runner
package carries a verbatim copy.

Accepted:

    key: scalar                  strings (bare or quoted), ints, floats, true/false/null
    key: [a, "b c", 3]           inline lists
    key:                         block lists
      - item
      - "quoted item"
    key:                         nested mappings, by indentation, any depth
      sub: value
      list: [x, y]
    # comments and blank lines anywhere

Not accepted (an error names the line): block scalars (`|`, `>`), anchors,
multi-document files, tabs for indentation, flow mappings (`{a: 1}`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DELIMITER = "---"

_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(?:\s+(.*))?$")


class FrontmatterError(ValueError):
    def __init__(self, message: str, line: int | None = None) -> None:
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


@dataclass
class Document:
    """The parsed header and the body that follows it."""

    meta: dict[str, Any]
    body: str
    has_frontmatter: bool


def split(text: str) -> tuple[list[str] | None, str]:
    """Return (header lines, body). Header is None when there is no frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != DELIMITER:
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() == DELIMITER:
            body = "\n".join(lines[index + 1:])
            return lines[1:index], body.lstrip("\n")
    raise FrontmatterError("frontmatter opened with --- but never closed", len(lines))


def parse(text: str) -> Document:
    header, body = split(text)
    if header is None:
        return Document(meta={}, body=body, has_frontmatter=False)
    return Document(meta=parse_mapping(header), body=body, has_frontmatter=True)


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value == "" or value in ("null", "~"):
        return None
    if value in ("true", "True"):
        return True
    if value in ("false", "False"):
        return False
    if (value.startswith('"') and value.endswith('"') and len(value) >= 2) or (
        value.startswith("'") and value.endswith("'") and len(value) >= 2
    ):
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
        return inner
    if value.startswith("[") and value.endswith("]"):
        return _parse_inline_list(value[1:-1])
    if value.startswith("{"):
        raise FrontmatterError("flow mappings are not supported; use indented keys")
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", value):
        return float(value)
    return value


def _parse_inline_list(inner: str) -> list[Any]:
    items: list[Any] = []
    current: list[str] = []
    quote: str | None = None
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == ",":
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    if current or items:
        items.append("".join(current))
    return [parse_scalar(item) for item in items if item.strip() != ""]


def _strip_comment(line: str) -> str:
    """Drop a trailing ` # comment` outside quotes."""
    quote: str | None = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index].rstrip()
    return line


def parse_mapping(lines: list[str], *, offset: int = 2) -> dict[str, Any]:
    """Parse header lines into a dict. `offset` is the file line of lines[0]."""
    entries: list[tuple[int, int, str]] = []          # (indent, line number, text)
    for number, raw in enumerate(lines, start=offset):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise FrontmatterError("tabs are not allowed for indentation", number)
        text = _strip_comment(raw.rstrip())
        if not text.strip():
            continue
        entries.append((len(text) - len(text.lstrip(" ")), number, text.strip()))
    result, consumed = _parse_block(entries, 0, entries[0][0] if entries else 0)
    if consumed != len(entries):
        indent, number, text = entries[consumed]
        raise FrontmatterError(f"unexpected indentation before {text!r}", number)
    return result


def _parse_block(entries: list[tuple[int, int, str]], start: int, indent: int) -> tuple[Any, int]:
    index = start
    if index < len(entries) and entries[index][2].startswith("- "):
        return _parse_block_list(entries, index, indent)
    mapping: dict[str, Any] = {}
    while index < len(entries):
        item_indent, number, text = entries[index]
        if item_indent < indent:
            break
        if item_indent > indent:
            raise FrontmatterError(f"unexpected indentation before {text!r}", number)
        match = _KEY.match(text)
        if not match:
            raise FrontmatterError(f"expected `key: value`, got {text!r}", number)
        key, raw_value = match.group(1), match.group(2)
        index += 1
        if raw_value is None or raw_value.strip() == "":
            if index < len(entries) and entries[index][0] > indent:
                value, index = _parse_block(entries, index, entries[index][0])
            else:
                value = None
        else:
            if raw_value.strip() in ("|", ">", "|-", ">-"):
                raise FrontmatterError("block scalars are not supported; put long text in the body", number)
            value = parse_scalar(raw_value)
        if key in mapping:
            raise FrontmatterError(f"duplicate key {key!r}", number)
        mapping[key] = value
    return mapping, index


def _parse_block_list(entries: list[tuple[int, int, str]], start: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    index = start
    while index < len(entries):
        item_indent, number, text = entries[index]
        if item_indent < indent:
            break
        if item_indent > indent or not text.startswith("- "):
            raise FrontmatterError(f"expected a `- item` line, got {text!r}", number)
        payload = text[2:].strip()
        index += 1
        if _KEY.match(payload) and not payload.startswith(("'", '"')):
            # A list of mappings: `- tool: x` followed by deeper `args:` lines.
            key_match = _KEY.match(payload)
            first = {key_match.group(1): parse_scalar(key_match.group(2) or "")}
            nested_indent = indent + 2
            if index < len(entries) and entries[index][0] >= nested_indent and not entries[index][2].startswith("- "):
                rest, index = _parse_block(entries, index, entries[index][0])
                first.update(rest)
            items.append(first)
        else:
            items.append(parse_scalar(payload))
    return items, index


def dump_mapping(mapping: dict[str, Any], *, indent: int = 0) -> str:
    """Serialize a dict in the subset above, for generators."""
    return "\n".join(_dump_lines(mapping, indent))


def _dump_lines(mapping: dict[str, Any], indent: int) -> list[str]:
    lines: list[str] = []
    pad = " " * indent
    for key, value in mapping.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.extend(_dump_lines(value, indent + 2))
        elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            lines.append(f"{pad}{key}:")
            for item in value:
                item_lines = _dump_lines(item, indent + 4)
                if item_lines:
                    item_lines[0] = f"{pad}  - " + item_lines[0].lstrip()
                lines.extend(item_lines)
        elif isinstance(value, list):
            lines.append(f"{pad}{key}: [{', '.join(_dump_scalar(v) for v in value)}]")
        else:
            lines.append(f"{pad}{key}: {_dump_scalar(value)}")
    return lines


def _dump_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or re.search(r'[:#\[\]{},"\']|^\s|\s$', text) or text in ("true", "false", "null"):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def dump(meta: dict[str, Any], body: str) -> str:
    return f"{DELIMITER}\n{dump_mapping(meta)}\n{DELIMITER}\n\n{body.rstrip()}\n"
