from __future__ import annotations

from typing import Any


def clean_tool_name(name: object) -> str:
    return str(name).strip() if name is not None else ""


def normalize_tool_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(arguments)
    if name in {"Read", "Write", "Edit", "Grep", "Glob"} and "path" not in normalized:
        for alias in ("file_path", "filepath", "dir", "directory"):
            if alias in normalized:
                normalized["path"] = normalized.pop(alias)
                break
    if name == "Glob":
        normalized.setdefault("path", ".")
    if name == "Grep":
        normalized.setdefault("path", ".")
    return normalized
