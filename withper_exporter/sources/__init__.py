"""取得元ソースのレジストリ。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Record, Source, SourceError, in_window, sort_records
from .jsonl import JsonlSource, JsonSource
from .sqlite_source import SqliteSource
from .whisperdir import WhisperDirSource

SOURCE_TYPES: dict[str, type[Source]] = {
    cls.type_name: cls
    for cls in (WhisperDirSource, JsonlSource, JsonSource, SqliteSource)
}

__all__ = [
    "Record",
    "Source",
    "SourceError",
    "SOURCE_TYPES",
    "build_source",
    "in_window",
    "sort_records",
]


def build_source(type_name: str, path: Path | None, options: dict[str, Any], tz) -> Source:
    try:
        cls = SOURCE_TYPES[type_name]
    except KeyError:
        known = ", ".join(sorted(SOURCE_TYPES))
        raise SourceError(
            f"未知の source.type です: {type_name!r} (使えるのは {known})"
        ) from None
    return cls(path, options, tz)
