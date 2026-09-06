from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

import yaml


def format_key(key: Any) -> str:
    text = str(key)
    if text.isidentifier():
        return text
    escaped = text.replace("\\", "\\\\").replace("'", "\\'")
    return f"['{escaped}']"


def join_path(base: str, key: Any, *, index: bool = False) -> str:
    if index:
        return f"{base}[{key}]" if base else f"[{key}]"
    formatted = format_key(key)
    if formatted.startswith("["):
        return f"{base}{formatted}"
    return f"{base}.{formatted}" if base else formatted


def structural_changes(old: Any, new: Any, path: str = "") -> list[dict[str, Any]]:
    if type(old) is not type(new):
        return [{"op": "modified", "path": path or "$", "old": old, "new": new}]
    if isinstance(old, dict):
        changes: list[dict[str, Any]] = []
        old_keys, new_keys = set(old), set(new)
        for key in sorted(old_keys - new_keys, key=str):
            changes.append(
                {"op": "removed", "path": join_path(path, key), "old": old[key]}
            )
        for key in sorted(new_keys - old_keys, key=str):
            changes.append(
                {"op": "added", "path": join_path(path, key), "new": new[key]}
            )
        for key in sorted(old_keys & new_keys, key=str):
            changes.extend(structural_changes(old[key], new[key], join_path(path, key)))
        return changes
    if isinstance(old, list):
        changes = []
        common = min(len(old), len(new))
        for index in range(common):
            changes.extend(
                structural_changes(
                    old[index], new[index], join_path(path, index, index=True)
                )
            )
        for index in range(len(old) - 1, common - 1, -1):
            changes.append(
                {
                    "op": "removed",
                    "path": join_path(path, index, index=True),
                    "old": old[index],
                }
            )
        for index in range(common, len(new)):
            changes.append(
                {
                    "op": "added",
                    "path": join_path(path, index, index=True),
                    "new": new[index],
                }
            )
        return changes
    return (
        []
        if old == new
        else [{"op": "modified", "path": path or "$", "old": old, "new": new}]
    )


def parse_structured(content: str, resource: str) -> Any:
    suffix = Path(resource).suffix.lower()
    if suffix == ".json":
        return json.loads(content)
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(content)
    raise ValueError("resource is not a structured format")


def text_diff(old: str, new: str, from_label: str, to_label: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=from_label,
            tofile=to_label,
        )
    )


def compare_content(
    old: str,
    new: str,
    resource: str,
    format: str = "auto",
    from_label: str = "from",
    to_label: str = "to",
) -> dict[str, Any]:
    if format not in {"auto", "structural", "text", "both"}:
        raise ValueError("format must be auto, structural, text, or both")
    suffix = Path(resource).suffix.lower()
    structured = suffix in {".yaml", ".yml", ".json"}
    result: dict[str, Any] = {}
    if format in {"structural", "both"} or (format == "auto" and structured):
        changes = structural_changes(
            parse_structured(old, resource), parse_structured(new, resource)
        )
        result["changes"] = changes
        result["summary"] = {
            operation: sum(1 for change in changes if change["op"] == operation)
            for operation in ("added", "modified", "removed")
        }
    if format in {"text", "both"} or (format == "auto" and not structured):
        result["text"] = text_diff(old, new, from_label, to_label)
    return result
