"""テスト用の共通ヘルパ。"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=9), "JST")


def dt(year=2026, month=9, day=11, hour=0, minute=0, second=0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=TZ)


def write_file(directory: Path, name: str, text: str, when: datetime) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    os.utime(path, (when.timestamp(), when.timestamp()))
    return path


def base_config(source_dir: Path, output_dir: Path, state_file: Path, **export) -> dict:
    config = {
        "source": {"type": "whisperdir", "path": str(source_dir)},
        "export": {
            "output_dir": str(output_dir),
            "interval": "1h",
            "align": True,
            "lookback": "24h",
            "grace": "0s",
            "encoding": "utf-8",
            "newline": "lf",
            "include_header": False,
        },
        "runtime": {
            "timezone": "Asia/Tokyo",
            "state_file": str(state_file),
            "log_file": False,
        },
    }
    config["export"].update(export)
    return config
