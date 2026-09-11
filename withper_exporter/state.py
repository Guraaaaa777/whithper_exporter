"""前回どこまでエクスポートしたかを保持する状態ファイル。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .timeutil import parse_timestamp

STATE_VERSION = 1


@dataclass
class State:
    last_window_end: datetime | None = None
    last_run_at: datetime | None = None
    exported_files: int = 0
    exported_records: int = 0

    def to_dict(self) -> dict:
        return {
            "version": STATE_VERSION,
            "last_window_end": _iso(self.last_window_end),
            "last_run_at": _iso(self.last_run_at),
            "exported_files": self.exported_files,
            "exported_records": self.exported_records,
        }


class StateStore:
    def __init__(self, path: Path, tz) -> None:
        self.path = path
        self.tz = tz

    def load(self) -> State:
        if not self.path.exists():
            return State()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 壊れていたら初期状態から。lookback でやり直せる。
            return State()
        if not isinstance(data, dict):
            return State()
        return State(
            last_window_end=_parse(data.get("last_window_end"), self.tz),
            last_run_at=_parse(data.get("last_run_at"), self.tz),
            exported_files=int(data.get("exported_files") or 0),
            exported_records=int(data.get("exported_records") or 0),
        )

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
        # 途中で落ちても壊れないよう一時ファイル経由で差し替える
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=self.path.name,
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self.path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value, tz) -> datetime | None:
    if not value:
        return None
    try:
        return parse_timestamp(value, tz)
    except Exception:
        return None
