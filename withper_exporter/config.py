"""config.toml の読み込みと既定値。"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from .timeutil import TimeParseError, parse_duration, resolve_tz

APP_NAME = "withper_exporter"
CONFIG_ENV = "WITHPER_EXPORTER_CONFIG"
CONFIG_FILENAME = "config.toml"

VALID_CONFLICT = {"overwrite", "append", "skip"}
NEWLINES = {"crlf": "\r\n", "lf": "\n", "native": None}


class ConfigError(RuntimeError):
    """設定が不正なとき。"""


def app_dir() -> Path:
    """設定・状態ファイルの既定の置き場所。"""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(base) / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / APP_NAME


def default_config_path() -> Path:
    return app_dir() / CONFIG_FILENAME


@dataclass
class SourceConfig:
    type: str = "whisperdir"
    path: Path | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExportConfig:
    output_dir: Path = Path("export")
    interval: timedelta = timedelta(hours=1)
    align: bool = True
    lookback: timedelta = timedelta(hours=24)
    grace: timedelta = timedelta(0)
    encoding: str = "utf-8-sig"
    newline: str = "crlf"
    include_header: bool = True
    line_prefix_format: str = "[%H:%M:%S] "
    separator: str = ""
    skip_empty: bool = True
    on_conflict: str = "overwrite"
    max_windows_per_run: int = 500
    filename_suffix: str = ".txt"

    @property
    def newline_chars(self) -> str | None:
        return NEWLINES[self.newline]


@dataclass
class RuntimeConfig:
    timezone: str = "local"
    state_file: Path = field(default_factory=lambda: app_dir() / "state.json")
    log_file: Path | None = field(default_factory=lambda: app_dir() / "withper_exporter.log")
    log_level: str = "INFO"
    log_max_bytes: int = 1_000_000
    log_backup_count: int = 3


@dataclass
class Config:
    source: SourceConfig
    export: ExportConfig
    runtime: RuntimeConfig
    path: Path | None = None

    @property
    def tz(self):
        return resolve_tz(self.runtime.timezone)


def load_config(path: Path | None = None) -> Config:
    """config.toml を読む。path 省略時は環境変数→既定パスの順で探す。"""
    config_path = resolve_config_path(path)
    if not config_path.exists():
        raise ConfigError(
            f"設定ファイルが見つかりません: {config_path}\n"
            f"`python -m {APP_NAME} init` で雛形を作成してください。"
        )
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path}: TOML の文法エラー: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{config_path}: 読み取りに失敗しました: {exc}") from exc

    return build_config(raw, config_path)


def resolve_config_path(path: Path | None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    env_value = os.environ.get(CONFIG_ENV)
    if env_value:
        return Path(env_value).expanduser()
    local = Path.cwd() / CONFIG_FILENAME
    if local.exists():
        return local
    return default_config_path()


def build_config(raw: dict[str, Any], config_path: Path | None = None) -> Config:
    base_dir = config_path.parent if config_path else Path.cwd()

    source_raw = _section(raw, "source")
    source = SourceConfig(
        type=str(source_raw.get("type", "whisperdir")),
        path=_maybe_path(source_raw.get("path"), base_dir),
        options=dict(source_raw.get("options") or {}),
    )

    export_raw = _section(raw, "export")
    defaults = ExportConfig()
    export = ExportConfig(
        output_dir=_maybe_path(export_raw.get("output_dir"), base_dir) or defaults.output_dir,
        interval=_duration(export_raw, "interval", defaults.interval),
        align=bool(export_raw.get("align", defaults.align)),
        lookback=_duration(export_raw, "lookback", defaults.lookback),
        grace=_duration(export_raw, "grace", defaults.grace, allow_zero=True),
        encoding=str(export_raw.get("encoding", defaults.encoding)),
        newline=str(export_raw.get("newline", defaults.newline)).lower(),
        include_header=bool(export_raw.get("include_header", defaults.include_header)),
        line_prefix_format=str(
            export_raw.get("line_prefix_format", defaults.line_prefix_format)
        ),
        separator=str(export_raw.get("separator", defaults.separator)),
        skip_empty=bool(export_raw.get("skip_empty", defaults.skip_empty)),
        on_conflict=str(export_raw.get("on_conflict", defaults.on_conflict)).lower(),
        max_windows_per_run=int(
            export_raw.get("max_windows_per_run", defaults.max_windows_per_run)
        ),
        filename_suffix=str(export_raw.get("filename_suffix", defaults.filename_suffix)),
    )

    runtime_raw = _section(raw, "runtime")
    runtime_defaults = RuntimeConfig()
    log_file_value = runtime_raw.get("log_file", runtime_defaults.log_file)
    runtime = RuntimeConfig(
        timezone=str(runtime_raw.get("timezone", runtime_defaults.timezone)),
        state_file=_maybe_path(runtime_raw.get("state_file"), base_dir)
        or runtime_defaults.state_file,
        log_file=None if log_file_value in (None, "", False) else _maybe_path(
            log_file_value, base_dir
        ),
        log_level=str(runtime_raw.get("log_level", runtime_defaults.log_level)).upper(),
        log_max_bytes=int(runtime_raw.get("log_max_bytes", runtime_defaults.log_max_bytes)),
        log_backup_count=int(
            runtime_raw.get("log_backup_count", runtime_defaults.log_backup_count)
        ),
    )

    config = Config(source=source, export=export, runtime=runtime, path=config_path)
    validate(config)
    return config


def validate(config: Config) -> None:
    from .sources import SOURCE_TYPES

    if config.source.type not in SOURCE_TYPES:
        known = ", ".join(sorted(SOURCE_TYPES))
        raise ConfigError(
            f"source.type が不正です: {config.source.type!r} (使えるのは {known})"
        )
    if config.export.newline not in NEWLINES:
        raise ConfigError(
            f"export.newline が不正です: {config.export.newline!r} "
            f"(使えるのは {', '.join(NEWLINES)})"
        )
    if config.export.on_conflict not in VALID_CONFLICT:
        raise ConfigError(
            f"export.on_conflict が不正です: {config.export.on_conflict!r} "
            f"(使えるのは {', '.join(sorted(VALID_CONFLICT))})"
        )
    if config.export.max_windows_per_run < 1:
        raise ConfigError("export.max_windows_per_run は1以上である必要があります")
    # ファイル名が YYYYMMDDhhmm-YYYYMMDDhhmm と分単位なので、
    # 秒単位の区切りだと同名ファイルができてしまう
    interval_seconds = config.export.interval.total_seconds()
    if interval_seconds < 60 or interval_seconds % 60:
        raise ConfigError(
            f"export.interval は1分以上かつ分単位である必要があります "
            f"(指定値: {config.export.interval})。"
            "ファイル名が分までしか表せないためです。"
        )
    try:
        "".encode(config.export.encoding)
    except LookupError as exc:
        raise ConfigError(f"export.encoding が不正です: {config.export.encoding!r}") from exc
    try:
        config.tz
    except TimeParseError as exc:
        raise ConfigError(str(exc)) from exc


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] はテーブルである必要があります")
    return value


def _maybe_path(value: Any, base_dir: Path) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _duration(
    raw: dict[str, Any], key: str, default: timedelta, allow_zero: bool = False
) -> timedelta:
    if key not in raw:
        return default
    try:
        return parse_duration(raw[key], allow_zero=allow_zero)
    except TimeParseError as exc:
        raise ConfigError(f"export.{key}: {exc}") from exc
