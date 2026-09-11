"""Whisper の出力ファイルが溜まるフォルダを取得元にするソース。

Windows の Whisper 系デスクトップアプリ（whisper CLI / whisper.cpp /
WhisperDesktop / Buzz など）は、文字起こし結果を出力フォルダに
.txt / .json / .srt / .vtt として書き出す。このソースはそのフォルダを見て、
ファイルの更新時刻をレコードの時刻として扱う。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..timeutil import TimeParseError, parse_timestamp
from .base import Record, Source, SourceError, make_id

TEXT_SUFFIXES = {".txt", ".text", ".md"}
JSON_SUFFIXES = {".json"}
SUBTITLE_SUFFIXES = {".srt", ".vtt"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | JSON_SUFFIXES | SUBTITLE_SUFFIXES
#: 同じ basename が複数形式であるときに優先して使う順番
DEFAULT_PREFERENCE = (".txt", ".json", ".srt", ".vtt", ".text", ".md")

_SRT_TIME = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)
_SRT_INDEX = re.compile(r"^\d+$")


class WhisperDirSource(Source):
    type_name = "whisperdir"

    def fetch(self, start: datetime, end: datetime) -> Iterable[Record]:
        for path in self._candidate_files():
            base = self._file_timestamp(path)
            if base is None:
                continue
            # セグメント展開しない場合、ファイル1件の時刻で窓判定できるので先に枝刈り
            if not self._segments_enabled() and not (start <= base < end):
                continue
            try:
                yield from self._records_from_file(path, base)
            except SourceError:
                raise
            except OSError as exc:
                raise SourceError(f"{path}: 読み取りに失敗しました: {exc}") from exc

    def describe(self) -> str:
        return f"whisperdir({self.path}, glob={self.option('glob', '*')})"

    # -- ファイル列挙 --------------------------------------------------------

    def _candidate_files(self) -> list[Path]:
        files = self.resolve_files(default_glob="*")
        allowed = self.option("suffixes")
        if allowed:
            wanted = {s if s.startswith(".") else f".{s}" for s in allowed}
        else:
            wanted = SUPPORTED_SUFFIXES
        matched = [p for p in files if p.suffix.lower() in wanted]
        if self.option("dedupe_by_stem", True):
            matched = self._pick_one_per_stem(matched)
        return matched

    def _pick_one_per_stem(self, files: list[Path]) -> list[Path]:
        """Whisper は1つの音声から .txt/.json/.srt/.vtt を同時に吐くことがある。

        同じ basename のものは1つだけ採用し、二重計上を防ぐ。
        """
        preference = [
            s.lower() if s.startswith(".") else f".{s.lower()}"
            for s in self.option("prefer_suffixes", DEFAULT_PREFERENCE)
        ]

        def rank(path: Path) -> tuple[int, str]:
            suffix = path.suffix.lower()
            index = preference.index(suffix) if suffix in preference else len(preference)
            return (index, path.name)

        groups: dict[tuple[Path, str], Path] = {}
        for path in files:
            key = (path.parent, path.stem)
            current = groups.get(key)
            if current is None or rank(path) < rank(current):
                groups[key] = path
        return sorted(groups.values())

    def _segments_enabled(self) -> bool:
        return bool(self.option("segments", False))

    # -- 時刻の決定 ----------------------------------------------------------

    def _file_timestamp(self, path: Path) -> datetime | None:
        mode = str(self.option("timestamp_from", "mtime")).lower()
        if mode == "filename":
            return self._timestamp_from_filename(path)
        try:
            stat = path.stat()
        except OSError as exc:
            raise SourceError(f"{path}: stat に失敗しました: {exc}") from exc
        epoch = stat.st_ctime if mode == "ctime" else stat.st_mtime
        return datetime.fromtimestamp(epoch, tz=self.tz)

    def _timestamp_from_filename(self, path: Path) -> datetime | None:
        pattern = self.option("filename_regex")
        stem = path.stem
        if pattern:
            match = re.search(pattern, stem)
            if not match:
                return None
            stem = match.group("ts") if "ts" in (match.groupdict() or {}) else match.group(0)
        fmt = self.option("filename_format")
        try:
            return parse_timestamp(stem, self.tz, fmt)
        except TimeParseError as exc:
            if self.option("skip_unparsable_names", True):
                return None
            raise SourceError(f"{path}: ファイル名から時刻を読めません: {exc}") from exc

    # -- 本文の取り出し ------------------------------------------------------

    def _records_from_file(self, path: Path, base: datetime) -> Iterator[Record]:
        raw = self._read_text(path)
        suffix = path.suffix.lower()
        origin = str(path)

        if suffix in JSON_SUFFIXES:
            segments = _json_segments(raw, path)
        elif suffix in SUBTITLE_SUFFIXES:
            segments = _subtitle_segments(raw)
        else:
            segments = [(None, raw)]

        if self._segments_enabled():
            for offset, text in segments:
                text = text.strip()
                if not text:
                    continue
                timestamp = base + timedelta(seconds=offset or 0.0)
                yield Record(
                    timestamp=timestamp,
                    text=text,
                    id=make_id(timestamp, text),
                    meta={"_origin": origin, "file": path.name, "offset": offset},
                )
            return

        joiner = self.option("segment_joiner", "\n")
        body = joiner.join(text.strip() for _, text in segments if text.strip()).strip()
        if not body:
            return
        yield Record(
            timestamp=base,
            text=body,
            id=make_id(base, body),
            meta={"_origin": origin, "file": path.name},
        )

    def _read_text(self, path: Path) -> str:
        encodings = self.option("input_encoding")
        if isinstance(encodings, str):
            candidates = [encodings]
        elif encodings:
            candidates = list(encodings)
        else:
            # Whisper 系は UTF-8 が基本だが、Windows のツールは cp932 のことがある
            candidates = ["utf-8-sig", "cp932"]
        last_error: Exception | None = None
        for encoding in candidates:
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError as exc:
                last_error = exc
        raise SourceError(
            f"{path}: 文字コードを判別できません（試したもの: {candidates}）"
        ) from last_error


def _json_segments(raw: str, path: Path) -> list[tuple[float | None, str]]:
    """Whisper の JSON 出力からセグメントを取り出す。"""
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceError(f"{path}: JSON として読めません: {exc}") from exc

    if isinstance(data, list):
        segments = data
    elif isinstance(data, dict):
        segments = data.get("segments")
        if not isinstance(segments, list):
            text = data.get("text")
            if isinstance(text, str):
                return [(None, text)]
            raise SourceError(f"{path}: 'segments' も 'text' も見つかりません")
    else:
        raise SourceError(f"{path}: 想定外の JSON 構造です")

    result: list[tuple[float | None, str]] = []
    for segment in segments:
        if isinstance(segment, str):
            result.append((None, segment))
            continue
        if not isinstance(segment, dict):
            continue
        text = segment.get("text")
        if not isinstance(text, str):
            continue
        start = segment.get("start")
        # whisper.cpp は offsets.from をミリ秒で持つ
        if start is None and isinstance(segment.get("offsets"), dict):
            from_ms = segment["offsets"].get("from")
            start = float(from_ms) / 1000 if isinstance(from_ms, (int, float)) else None
        result.append((float(start) if isinstance(start, (int, float)) else None, text))
    return result


def _subtitle_segments(raw: str) -> list[tuple[float | None, str]]:
    """SRT / VTT からタイムコードを剥がして本文を取り出す。"""
    result: list[tuple[float | None, str]] = []
    current_start: float | None = None
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            result.append((current_start, " ".join(buffer)))
            buffer.clear()

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.upper().startswith("WEBVTT") or stripped.startswith("NOTE "):
            continue
        match = _SRT_TIME.search(stripped)
        if match:
            flush()
            current_start = (
                int(match.group("h")) * 3600
                + int(match.group("m")) * 60
                + int(match.group("s"))
                + int(match.group("ms").ljust(3, "0")) / 1000
            )
            continue
        if _SRT_INDEX.match(stripped) and not buffer:
            continue
        buffer.append(stripped)
    flush()
    return result
