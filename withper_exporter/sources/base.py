"""取得元（ソース）の共通インタフェース。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from ..timeutil import TimeParseError, parse_timestamp


class SourceError(RuntimeError):
    """取得元の読み取りに失敗したとき。"""


@dataclass(frozen=True)
class Record:
    """文字起こし1件分。"""

    timestamp: datetime
    text: str
    id: str
    meta: dict[str, Any] = field(default_factory=dict)

    def sort_key(self) -> tuple[datetime, str]:
        return (self.timestamp, self.id)


def make_id(timestamp: datetime, text: str, explicit: Any = None) -> str:
    """重複排除用のID。ソース側にIDが無ければ内容から生成する。"""
    if explicit not in (None, ""):
        return str(explicit)
    digest = hashlib.sha1(
        f"{timestamp.isoformat()}\x00{text}".encode("utf-8", "replace")
    ).hexdigest()
    return digest[:16]


class Source:
    """取得元の基底クラス。

    fetch() は [start, end) に入るレコードを返す。範囲外を含めて返しても
    エクスポータ側で捨てるが、可能ならソース側で絞るほうが速い。
    """

    #: config の source.type に書く名前
    type_name: str = ""

    def __init__(self, path: Path | None, options: dict[str, Any], tz) -> None:
        self.path = path
        self.options = options
        self.tz = tz

    def fetch(self, start: datetime, end: datetime) -> Iterable[Record]:
        raise NotImplementedError

    def describe(self) -> str:
        return f"{self.type_name}({self.path})"

    # -- 派生クラス向けヘルパ ------------------------------------------------

    def option(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)

    def require_path(self) -> Path:
        if self.path is None:
            raise SourceError(f"source.type='{self.type_name}' には path の指定が必要です")
        return self.path

    def resolve_files(self, default_glob: str = "*") -> list[Path]:
        """path がディレクトリなら glob で、ファイルならそれ自体を返す。"""
        path = self.require_path()
        pattern = self.option("glob", default_glob)
        if path.is_dir():
            recursive = bool(self.option("recursive", False))
            globber = path.rglob if recursive else path.glob
            return sorted(p for p in globber(pattern) if p.is_file())
        if path.is_file():
            return [path]
        # ワイルドカードを直接 path に書いた場合
        if any(ch in str(path) for ch in "*?["):
            parent = path.parent
            return sorted(p for p in parent.glob(path.name) if p.is_file())
        raise SourceError(f"取得元が見つかりません: {path}")

    def map_record(self, row: dict[str, Any], origin: str) -> Record | None:
        """辞書1件を Record に変換する。text が空なら None。"""
        ts_field = self.option("timestamp_field", "timestamp")
        text_field = self.option("text_field", "text")
        id_field = self.option("id_field", "id")
        ts_format = self.option("timestamp_format")

        raw_ts = _pick(row, ts_field)
        if raw_ts is None:
            raise SourceError(
                f"{origin}: タイムスタンプ項目 {ts_field!r} が見つかりません "
                f"(存在する項目: {sorted(row)[:10]})"
            )
        raw_text = _pick(row, text_field)
        if raw_text is None:
            raise SourceError(
                f"{origin}: テキスト項目 {text_field!r} が見つかりません "
                f"(存在する項目: {sorted(row)[:10]})"
            )

        text = str(raw_text).strip()
        if not text:
            return None

        try:
            timestamp = parse_timestamp(raw_ts, self.tz, ts_format)
        except TimeParseError as exc:
            raise SourceError(f"{origin}: {exc}") from exc

        meta = {k: v for k, v in row.items() if k not in {ts_field, text_field, id_field}}
        meta["_origin"] = origin
        return Record(
            timestamp=timestamp,
            text=text,
            id=make_id(timestamp, text, _pick(row, id_field)),
            meta=meta,
        )


def _pick(row: dict[str, Any], field_name: str) -> Any:
    """'a.b.c' のようなドット区切りにも対応した取り出し。"""
    if field_name in row:
        return row[field_name]
    if "." not in field_name:
        return None
    current: Any = row
    for part in field_name.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def in_window(records: Iterable[Record], start: datetime, end: datetime) -> Iterator[Record]:
    for record in records:
        if start <= record.timestamp < end:
            yield record


def sort_records(records: Sequence[Record]) -> list[Record]:
    return sorted(records, key=Record.sort_key)
