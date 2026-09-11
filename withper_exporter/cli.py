"""コマンドラインインタフェース。"""

from __future__ import annotations

import argparse
import logging
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import (
    APP_NAME,
    CONFIG_ENV,
    Config,
    ConfigError,
    app_dir,
    load_config,
    resolve_config_path,
)
from .exporter import Exporter, pending_windows
from .logging_setup import setup_logging
from .probe import probe_path
from .scheduler import Daemon
from .sources import SourceError
from .template import render_template

LOGGER = logging.getLogger(__name__)


def _add_common_options(parser: argparse.ArgumentParser, suppress: bool) -> None:
    """全コマンド共通のオプション。

    サブコマンド側にも同じものを生やしておくと `run --quiet` のような
    自然な並びが通る。既定値を SUPPRESS にしておかないと、指定しなかった
    サブコマンド側の既定値が親の指定を打ち消してしまう。
    """
    kwargs = {"default": argparse.SUPPRESS} if suppress else {}
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help=f"設定ファイルのパス (既定: 環境変数 {CONFIG_ENV} → {app_dir() / 'config.toml'})",
        **kwargs,
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="詳細ログを出す", **kwargs
    )
    parser.add_argument(
        "--quiet", action="store_true", help="画面へのログ出力を止める", **kwargs
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"python -m {APP_NAME}",
        description="Whisper の文字起こし結果を一定時間ごとにテキストへ書き出します。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _add_common_options(parser, suppress=False)

    common = argparse.ArgumentParser(add_help=False)
    _add_common_options(common, suppress=True)

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="設定ファイルの雛形を作る", parents=[common])
    p_init.add_argument("--force", action="store_true", help="既存ファイルを上書きする")
    p_init.add_argument("--source-path", type=Path, help="Whisper の出力フォルダ")
    p_init.add_argument("--output-dir", type=Path, help="テキストの書き出し先")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="未処理のウィンドウを1回分まとめて書き出す", parents=[common])
    p_run.add_argument("--dry-run", action="store_true", help="書き込まず結果だけ表示する")
    p_run.add_argument(
        "--flush",
        action="store_true",
        help="進行中のウィンドウも現在時刻までで書き出す",
    )
    p_run.set_defaults(func=cmd_run)

    p_daemon = sub.add_parser("daemon", help="常駐して定期的に書き出す", parents=[common])
    p_daemon.add_argument(
        "--flush-on-exit",
        action="store_true",
        help="終了時に進行中のウィンドウも書き出す",
    )
    p_daemon.set_defaults(func=cmd_daemon)

    p_status = sub.add_parser("status", help="設定と進捗を表示する", parents=[common])
    p_status.set_defaults(func=cmd_status)

    p_probe = sub.add_parser("probe", help="取得元フォルダを調べて設定案を出す", parents=[common])
    p_probe.add_argument("path", type=Path, help="Whisper の出力フォルダ／ファイル")
    p_probe.add_argument("--limit", type=int, default=5, help="表示するサンプル件数")
    p_probe.set_defaults(func=cmd_probe)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # SUPPRESS 既定のため、どちらにも指定が無い場合は属性自体が存在しない
    args.config = getattr(args, "config", None)
    args.verbose = getattr(args, "verbose", False)
    args.quiet = getattr(args, "quiet", False)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"設定エラー: {exc}", file=sys.stderr)
        return 2
    except SourceError as exc:
        print(f"取得元エラー: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


# -- 各コマンド --------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    target = resolve_config_path(args.config)
    if target.exists() and not args.force:
        print(f"既に存在します: {target}（上書きするなら --force）", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_template(source_path=args.source_path, output_dir=args.output_dir),
        encoding="utf-8",
    )
    print(f"設定ファイルを作成しました: {target}")
    print("source.path と export.output_dir を実環境に合わせて編集してください。")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = _load(args)
    exporter = Exporter(config)
    result = exporter.run_once(dry_run=args.dry_run, flush=args.flush)

    if not result.windows:
        print("書き出し対象のウィンドウはまだありません。")
        return 0

    # 空ウィンドウは数が多くなりがちなので、既定では件数だけ伝える
    shown = result.windows if args.verbose else [w for w in result.windows if w.record_count]
    for window in shown:
        mark = "書き出し" if window.written else f"スキップ({window.skipped_reason})"
        print(f"{window.filename}  {window.record_count:>4}件  {mark}")

    empty = len(result.windows) - len([w for w in result.windows if w.record_count])
    if empty and not args.verbose:
        print(f"（レコード0件のウィンドウ {empty} 個は省略）")
    if args.dry_run:
        print("(--dry-run のため実際には書き込んでいません)")
    else:
        print(f"合計 {result.written_files} ファイル / {result.written_records} 件")
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    config = _load(args)
    daemon = Daemon(Exporter(config), flush_on_exit=args.flush_on_exit)
    daemon.install_signal_handlers()
    return daemon.run()


def cmd_status(args: argparse.Namespace) -> int:
    config = _load(args, console=False)
    exporter = Exporter(config)
    state = exporter.state_store.load()
    now = datetime.now(tz=exporter.tz)

    rows = [
        ("設定ファイル", config.path),
        ("取得元", exporter.source.describe()),
        ("出力先", config.export.output_dir),
        ("間隔", config.export.interval),
        ("猶予(grace)", config.export.grace),
        ("タイムゾーン", now.strftime("%Z%z")),
        ("状態ファイル", config.runtime.state_file),
        ("ログ", config.runtime.log_file or "(無効)"),
        ("最終実行", state.last_run_at or "(未実行)"),
        ("処理済み境界", state.last_window_end or "(未処理)"),
        ("累計ファイル", state.exported_files),
        ("累計レコード", state.exported_records),
        (
            "未処理ウィンドウ",
            pending_windows(state, now, config.export.interval, config.export.grace),
        ),
    ]
    width = max(_display_width(label) for label, _ in rows)
    for label, value in rows:
        print(f"{label}{' ' * (width - _display_width(label))} : {value}")

    source_path = config.source.path
    if source_path is not None and not source_path.exists():
        print(f"\n警告: 取得元が存在しません: {source_path}", file=sys.stderr)
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    report = probe_path(args.path, limit=args.limit)
    print(report)
    return 0


def _display_width(text: str) -> int:
    """全角文字を2桁として数える（表の桁合わせ用）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _load(args: argparse.Namespace, console: bool = True) -> Config:
    config = load_config(args.config)
    setup_logging(
        config.runtime,
        console=console and not args.quiet,
        verbose=args.verbose,
    )
    return config
