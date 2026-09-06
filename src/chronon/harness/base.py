from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class Issue:
    path: str
    message: str
    severity: Literal["error", "warning"] = "error"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def parse_content(content: str, path: str | Path) -> Any:
    suffix = Path(path).suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(content)
    if suffix == ".json":
        return json.loads(content)
    return content


def _json_path(parts: list[Any]) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def validate_content(
    content: str, path: str | Path, schema: dict[str, Any] | None = None
) -> list[Issue]:
    try:
        parsed = parse_content(content, path)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f"line {mark.line + 1}, column {mark.column + 1}" if mark else "$"
        return [Issue(location, str(getattr(exc, "problem", None) or exc))]
    except json.JSONDecodeError as exc:
        return [Issue(f"line {exc.lineno}, column {exc.colno}", exc.msg)]
    except (UnicodeError, ValueError) as exc:
        return [Issue("$", f"content is not valid UTF-8 text: {exc}")]
    if schema is None:
        return []
    validator = Draft202012Validator(schema)
    return [
        Issue(_json_path(list(error.absolute_path)), error.message)
        for error in sorted(
            validator.iter_errors(parsed),
            key=lambda item: str(list(item.absolute_path)),
        )
    ]
