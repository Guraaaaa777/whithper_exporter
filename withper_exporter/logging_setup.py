"""ログ出力の設定。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import RuntimeConfig

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(runtime: RuntimeConfig, console: bool = True, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else getattr(logging, runtime.log_level, logging.INFO)
    root = logging.getLogger()
    root.setLevel(min(level, logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(FORMAT)

    if runtime.log_file is not None:
        try:
            runtime.log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                runtime.log_file,
                maxBytes=runtime.log_max_bytes,
                backupCount=runtime.log_backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            root.addHandler(file_handler)
        except OSError as exc:  # ログが書けなくても本処理は続ける
            print(f"ログファイルを開けません ({runtime.log_file}): {exc}", file=sys.stderr)

    # pythonw.exe から起動すると stderr が None になることがある
    if console and sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(level)
        root.addHandler(stream_handler)

    if not root.handlers:
        root.addHandler(logging.NullHandler())
