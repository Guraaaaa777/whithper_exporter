"""時間ウィンドウごとにテキストファイルを書き出す中核処理。"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

from .config import Config
from .sources import Record, SourceError, build_source, in_window, sort_records
from .state import State, StateStore
from .timeutil import floor_to_interval, window_filename

LOGGER = logging.getLogger(__name__)


@dataclass
class WindowResult:
    """ウィンドウ1つ分のエクスポート結果。"""

    start: datetime
    end: datetime
    record_count: int
    path: Path | None = None
    written: bool = False
    skipped_reason: str | None = None

    @property
    def filename(self) -> str:
        return self.path.name if self.path else ""


@dataclass
class RunResult:
    """1回の実行（run）全体の結果。"""

    windows: list[WindowResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def written_files(self) -> int:
        return sum(1 for w in self.windows if w.written)

    @property
    def written_records(self) -> int:
        return sum(w.record_count for w in self.windows if w.written)


class Exporter:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.tz = config.tz
        self.source = build_source(
            config.source.type, config.source.path, config.source.options, self.tz
        )
        self.state_store = StateStore(config.runtime.state_file, self.tz)

    # -- 実行 ----------------------------------------------------------------

    def run_once(
        self, now: datetime | None = None, dry_run: bool = False, flush: bool = False
    ) -> RunResult:
        """未処理のウィンドウをまとめてエクスポートする。

        flush=True のときは、まだ閉じていない現在進行中のウィンドウも
        「開始〜現在時刻」として書き出す（手動実行・終了時向け）。
        """
        export = self.config.export
        now = now or datetime.now(tz=self.tz)
        state = self.state_store.load()

        cursor = self._start_cursor(state, now)
        deadline = now - export.grace
        result = RunResult(dry_run=dry_run)

        while cursor + export.interval <= deadline:
            if len(result.windows) >= export.max_windows_per_run:
                LOGGER.warning(
                    "1回の実行上限 %d ウィンドウに達しました。残りは次回に持ち越します。",
                    export.max_windows_per_run,
                )
                break
            window_end = cursor + export.interval
            window_result = self.export_window(cursor, window_end, dry_run=dry_run)
            result.windows.append(window_result)
            cursor = window_end
            if not dry_run:
                self._advance(state, cursor, window_result, now)

        if flush:
            # 進行中のウィンドウも書き出す。ここでも秒以下は切り捨てる
            # （落とした端数は次回の実行で拾われる）
            flush_end = deadline.replace(second=0, microsecond=0)
            if cursor < flush_end:
                window_result = self.export_window(cursor, flush_end, dry_run=dry_run)
                result.windows.append(window_result)
                if not dry_run:
                    self._advance(state, flush_end, window_result, now)

        if not dry_run:
            state.last_run_at = now
            self.state_store.save(state)

        return result

    def _advance(
        self, state: State, cursor: datetime, window: WindowResult, now: datetime
    ) -> None:
        state.last_window_end = cursor
        state.last_run_at = now
        if window.written:
            state.exported_files += 1
            state.exported_records += window.record_count
        self.state_store.save(state)

    def _start_cursor(self, state: State, now: datetime) -> datetime:
        export = self.config.export
        if state.last_window_end is not None:
            return state.last_window_end.astimezone(self.tz)
        start = now - export.lookback
        if export.align:
            return floor_to_interval(start, export.interval)
        # 非整列でもファイル名は分単位なので、秒以下は落としておく
        return start.replace(second=0, microsecond=0)

    # -- ウィンドウ単位 --------------------------------------------------------

    def export_window(
        self, start: datetime, end: datetime, dry_run: bool = False
    ) -> WindowResult:
        records = self.collect(start, end)
        export = self.config.export
        path = self.config.export.output_dir / window_filename(
            start, end, export.filename_suffix
        )

        if not records and export.skip_empty:
            LOGGER.debug("%s: レコード0件のため作成しません", path.name)
            return WindowResult(start, end, 0, path, False, "empty")

        if dry_run:
            return WindowResult(start, end, len(records), path, False, "dry-run")

        if path.exists() and export.on_conflict == "skip":
            LOGGER.info("%s: 既に存在するためスキップします", path.name)
            return WindowResult(start, end, len(records), path, False, "exists")

        body = self.render(records, start, end)
        append = path.exists() and export.on_conflict == "append"
        self._write(path, body, append=append)
        LOGGER.info("%s に %d 件を書き出しました", path, len(records))
        return WindowResult(start, end, len(records), path, True, None)

    def collect(self, start: datetime, end: datetime) -> list[Record]:
        try:
            fetched = self.source.fetch(start, end)
            records = list(in_window(fetched, start, end))
        except SourceError:
            raise
        except OSError as exc:
            raise SourceError(f"取得元の読み取りに失敗しました: {exc}") from exc
        return dedupe(sort_records(records))

    # -- 整形・書き込み --------------------------------------------------------

    def render(self, records: Sequence[Record], start: datetime, end: datetime) -> str:
        export = self.config.export
        blocks: list[str] = []

        if export.include_header:
            blocks.append(self._header(records, start, end))

        for record in records:
            prefix = (
                record.timestamp.strftime(export.line_prefix_format)
                if export.line_prefix_format
                else ""
            )
            blocks.append(f"{prefix}{record.text}")

        separator = "\n" + export.separator if export.separator else "\n"
        return separator.join(blocks).rstrip() + "\n"

    def _header(self, records: Sequence[Record], start: datetime, end: datetime) -> str:
        tz_label = start.strftime("%Z") or str(self.tz)
        lines = [
            "# withper / Whisper 文字起こしエクスポート",
            f"# 期間: {start:%Y-%m-%d %H:%M} - {end:%Y-%m-%d %H:%M} ({tz_label})",
            f"# 件数: {len(records)}",
            f"# 取得元: {self.source.describe()}",
        ]
        return "\n".join(lines)

    def _write(self, path: Path, body: str, append: bool) -> None:
        export = self.config.export
        path.parent.mkdir(parents=True, exist_ok=True)
        newline = export.newline_chars

        if append:
            with path.open("a", encoding=export.encoding, newline=newline) as handle:
                handle.write("\n" + body)
            return

        # 書き込み途中のファイルを他ツールに読ませないため、一時ファイル経由で置き換える
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding=export.encoding,
            newline=newline,
            dir=path.parent,
            prefix=path.stem,
            suffix=".part",
            delete=False,
        )
        try:
            with handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise


def dedupe(records: Iterable[Record]) -> list[Record]:
    """同一IDのレコードを1件に畳む（複数ファイルに同じ内容がある場合向け）。"""
    seen: set[str] = set()
    result: list[Record] = []
    for record in records:
        if record.id in seen:
            continue
        seen.add(record.id)
        result.append(record)
    return result


def pending_windows(
    state: State, now: datetime, interval: timedelta, grace: timedelta
) -> int:
    """未処理ウィンドウ数（status 表示用）。"""
    if state.last_window_end is None:
        return 0
    remaining = (now - grace) - state.last_window_end
    if remaining <= timedelta(0):
        return 0
    return int(remaining // interval)
