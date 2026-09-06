from __future__ import annotations

import ast
import re
from copy import deepcopy
from typing import Any

from .errors import PathError

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


def parse_path(path: str) -> list[str | int]:
    if not path or path == "$":
        return []
    parts: list[str | int] = []
    index = 0
    while index < len(path):
        if path[index] == ".":
            index += 1
            if index == len(path):
                raise PathError("path cannot end with a dot", path=path)
        if path[index] == "[":
            closing = index + 1
            quote = (
                path[closing]
                if closing < len(path) and path[closing] in "'\""
                else None
            )
            if quote:
                closing += 1
                escaped = False
                while closing < len(path):
                    char = path[closing]
                    if char == quote and not escaped:
                        break
                    escaped = char == "\\" and not escaped
                    if char != "\\":
                        escaped = False
                    closing += 1
                if (
                    closing >= len(path)
                    or closing + 1 >= len(path)
                    or path[closing + 1] != "]"
                ):
                    raise PathError("unterminated quoted key", path=path)
                try:
                    value = ast.literal_eval(path[index + 1 : closing + 1])
                except (ValueError, SyntaxError) as exc:
                    raise PathError("invalid quoted key", path=path) from exc
                parts.append(value)
                index = closing + 2
            else:
                closing = path.find("]", index + 1)
                if closing == -1:
                    raise PathError("unterminated list index", path=path)
                value = path[index + 1 : closing]
                if not value.isdigit():
                    raise PathError(
                        "list index must be a non-negative integer", path=path
                    )
                parts.append(int(value))
                index = closing + 1
        else:
            match = IDENTIFIER.match(path, index)
            if not match:
                raise PathError("invalid path syntax", path=path, offset=index)
            parts.append(match.group())
            index = match.end()
        if index < len(path) and path[index] not in ".[":
            raise PathError("invalid path syntax", path=path, offset=index)
    return parts


def get_value(document: Any, path: str) -> Any:
    current = document
    for part in parse_path(path):
        try:
            if isinstance(part, int):
                if not isinstance(current, list):
                    raise TypeError
                current = current[part]
            else:
                if not isinstance(current, dict):
                    raise TypeError
                current = current[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise PathError("path does not exist", path=path) from exc
    return current


def set_value(document: Any, path: str, value: Any) -> Any:
    parts = parse_path(path)
    if not parts:
        return value
    result = deepcopy(document)
    current = result
    for position, part in enumerate(parts[:-1]):
        next_part = parts[position + 1]
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                raise PathError("list index is out of range", path=path)
            current = current[part]
        else:
            if not isinstance(current, dict):
                raise PathError("path crosses a non-mapping value", path=path)
            if part not in current:
                if isinstance(next_part, int):
                    raise PathError("lists are not auto-created", path=path)
                current[part] = {}
            current = current[part]
    final = parts[-1]
    if isinstance(final, int):
        if not isinstance(current, list) or final >= len(current):
            raise PathError("list index is out of range", path=path)
        current[final] = value
    else:
        if not isinstance(current, dict):
            raise PathError("parent is not a mapping", path=path)
        current[final] = value
    return result


def unset_value(document: Any, path: str) -> Any:
    parts = parse_path(path)
    if not parts:
        raise PathError("cannot unset the document root", path=path)
    result = deepcopy(document)
    current = result
    for part in parts[:-1]:
        try:
            current = current[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise PathError("path does not exist", path=path) from exc
    final = parts[-1]
    try:
        if isinstance(final, int):
            current.pop(final)
        else:
            del current[final]
    except (KeyError, IndexError, TypeError) as exc:
        raise PathError("path does not exist", path=path) from exc
    return result
