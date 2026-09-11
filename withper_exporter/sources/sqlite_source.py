"""SQLite に履歴を持つアプリ向けのソース。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Iterable

from .base import Record, Source, SourceError


class SqliteSource(Source):
    type_name = "sqlite"

    def fetch(self, start: datetime, end: datetime) -> Iterable[Record]:
        path = self.require_path()
        if not path.exists():
            raise SourceError(f"SQLite ファイルが見つかりません: {path}")

        query = self.option("query")
        if not query:
            table = self.option("table")
            if not table:
                raise SourceError("sqlite ソースには table か query の指定が必要です")
            query = f"SELECT * FROM {table}"  # noqa: S608 - 設定由来のテーブル名

        # ロック中の DB でも読めるよう読み取り専用で開く
        uri = f"file:{path.as_posix()}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=5) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(query).fetchall()
        except sqlite3.Error as exc:
            raise SourceError(f"{path}: SQLite の読み取りに失敗しました: {exc}") from exc

        for index, row in enumerate(rows):
            record = self.map_record(dict(row), f"{path}#{index}")
            if record is not None:
                yield record

    def describe(self) -> str:
        return f"sqlite({self.path}, table={self.option('table')})"
