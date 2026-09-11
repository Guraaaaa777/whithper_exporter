"""`init` が書き出す config.toml の雛形。"""

from __future__ import annotations

import sys
from pathlib import Path

TEMPLATE = '''# withper_exporter 設定ファイル
# 相対パスはこのファイルのある場所からの相対になります。

[source]
# 取得元の種類: whisperdir / jsonl / json / sqlite
type = "whisperdir"
# Whisper が文字起こし結果（.txt/.json/.srt/.vtt）を書き出すフォルダ
path = {source_path}

[source.options]
# 対象ファイルの絞り込み
glob = "*"
recursive = false
# レコードの時刻の決め方: "mtime"（更新時刻） / "ctime" / "filename"
timestamp_from = "mtime"
# 拡張子を絞る場合（既定は .txt .json .srt .vtt）
# suffixes = [".txt", ".json"]
# 読み込み時の文字コード候補（上から順に試す）
# input_encoding = ["utf-8-sig", "cp932"]
# .json/.srt/.vtt をセグメント単位に分けて出力するなら true
segments = false

# timestamp_from = "filename" のときの例:
#   20260911_1432_meeting.txt から時刻を取る
# filename_regex = "(?P<ts>\\\\d{{8}}_\\\\d{{4}})"
# filename_format = "%Y%m%d_%H%M"

[export]
# テキストの書き出し先フォルダ
output_dir = {output_dir}
# ファイル1本がカバーする時間幅。"10m" / "30m" / "1h" / "1d" など
interval = "1h"
# 区切りを時刻の切りの良い位置に揃える（09:00-10:00 のように）
align = true
# 初回実行時に何時間さかのぼるか
lookback = "24h"
# ウィンドウが閉じてから書き出すまでの猶予（書き込み中のファイルを取りこぼさないため）
grace = "1m"
# 0件のウィンドウではファイルを作らない
skip_empty = true
# 出力の文字コード。Windows のメモ帳向けには utf-8-sig が無難
encoding = "utf-8-sig"
# 改行コード: crlf / lf / native
newline = "crlf"
# 先頭のヘッダ（期間・件数）を入れる
include_header = true
# 各レコードの行頭に付ける時刻。空文字なら付けない
line_prefix_format = "[%H:%M:%S] "
# レコード間に追加で入れる区切り（"" なら1行改行のみ）
separator = ""
# 同名ファイルがあったとき: overwrite / append / skip
on_conflict = "overwrite"

[runtime]
# "local" でOSのタイムゾーン。"Asia/Tokyo" のような指定も可
timezone = "local"
# 進捗の保存先（省略時はアプリ設定フォルダ）
# state_file = "state.json"
# ログファイル。false にすると無効
# log_file = "withper_exporter.log"
log_level = "INFO"
'''


def default_source_path() -> str:
    if sys.platform == "win32":
        return r"C:\Users\%USERNAME%\Documents\Whisper"
    return str(Path.home() / "whisper-output")


def default_output_dir() -> str:
    if sys.platform == "win32":
        return r"C:\Users\%USERNAME%\Documents\WhisperExport"
    return str(Path.home() / "whisper-export")


def render_template(source_path: Path | None = None, output_dir: Path | None = None) -> str:
    return TEMPLATE.format(
        source_path=_toml_path(source_path or default_source_path()),
        output_dir=_toml_path(output_dir or default_output_dir()),
    )


def _toml_path(value: Path | str) -> str:
    """Windows のバックスラッシュを壊さないよう TOML のリテラル文字列で書く。"""
    text = str(value)
    if "'" in text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"'{text}'"
