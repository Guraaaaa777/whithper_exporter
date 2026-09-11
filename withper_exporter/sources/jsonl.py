"""1行1JSON（JSON Lines）のログファイルを取得元にするソース。

アプリが履歴を .jsonl / .json で持っている場合に使う。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Iterator

from .base import Record, Source, SourceError


class JsonlSource(Source):
    type_name = "jsonl"

    def fetch(self, start: datetime, end: datetime) -> Iterable[Record]:
        strict = bool(self.option("strict", False))
        for path in self.resolve_files(default_glob="*.jsonl"):
            for lineno, line in enumerate(self._iter_lines(path), 1):
                origin = f"{path}:{lineno}"
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    if strict:
                        raise SourceError(f"{origin}: JSON として読めません: {exc}") from exc
                    continue
                if not isinstance(row, dict):
                    continue
                record = self.map_record(row, origin)
                if record is not None:
                    yield record

    def _iter_lines(self, path) -> Iterator[str]:
        encoding = self.option("input_encoding", "utf-8-sig")
        try:
            with path.open("r", encoding=encoding, errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        yield line
        except OSError as exc:
            raise SourceError(f"{path}: 読み取りに失敗しました: {exc}") from exc


class JsonSource(Source):
    """配列 or {"records": [...]} 形式の JSON ファイル。"""

    type_name = "json"

    def fetch(self, start: datetime, end: datetime) -> Iterable[Record]:
        for path in self.resolve_files(default_glob="*.json"):
            encoding = self.option("input_encoding", "utf-8-sig")
            try:
                raw = path.read_text(encoding=encoding, errors="replace")
            except OSError as exc:
                raise SourceError(f"{path}: 読み取りに失敗しました: {exc}") from exc
            try:
                data: Any = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SourceError(f"{path}: JSON として読めません: {exc}") from exc

            rows = self._extract_rows(data, path)
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                record = self.map_record(row, f"{path}[{index}]")
                if record is not None:
                    yield record

    def _extract_rows(self, data: Any, path) -> list[Any]:
        key = self.option("records_key")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if key:
                rows = data.get(key)
                if not isinstance(rows, list):
                    raise SourceError(f"{path}: records_key={key!r} が配列ではありません")
                return rows
            for candidate in ("records", "items", "history", "transcripts", "data"):
                if isinstance(data.get(candidate), list):
                    return data[candidate]
            return [data]
        raise SourceError(f"{path}: 想定外の JSON 構造です")
