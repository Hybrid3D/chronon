"""Lenient text handling for tracked content.

UTF-8 is the assumed encoding for every tracked document, but it is not a hard
requirement. Content that is not valid UTF-8 is decoded with PEP 383
``surrogateescape``: undecodable bytes become lone surrogate code points that
re-encode to the exact same bytes, so any byte sequence round-trips losslessly
through a Python ``str`` and Chronon's hashing, diffing and state logic keep
working unchanged.

The one place a surrogate-bearing string cannot go is JSON (``json.dumps``
raises on lone surrogates), so ``json_safe``/``json_safe_text`` sanitise strings
at the MCP and ``--json`` boundaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

WORKING_TEXT_ERRORS = "surrogateescape"


def read_working_text(path: Path) -> str:
    """Read a tracked file as text, preserving non-UTF-8 bytes as lone
    surrogates so they round-trip byte-for-byte on the next write."""
    return path.read_bytes().decode("utf-8", WORKING_TEXT_ERRORS)


def encode_working_text(text: str) -> bytes:
    """Inverse of :func:`read_working_text`: exact bytes back out."""
    return text.encode("utf-8", WORKING_TEXT_ERRORS)


def has_lone_surrogates(text: str) -> bool:
    """True if ``text`` carries surrogateescape bytes (not valid UTF-8)."""
    return any("\ud800" <= ch <= "\udfff" for ch in text)


def json_safe_text(text: str) -> str:
    """Return a form of ``text`` that ``json.dumps`` can always serialise."""
    if not has_lone_surrogates(text):
        return text
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def json_safe(value: Any) -> Any:
    """Recursively apply :func:`json_safe_text` to every string in ``value``."""
    if isinstance(value, str):
        return json_safe_text(value)
    if isinstance(value, dict):
        return {json_safe(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return tuple(json_safe(item) for item in value)
    return value
