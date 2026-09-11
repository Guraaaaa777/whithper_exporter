# withper_exporter

Whisper で文字起こししたテキストを、一定時間ごとに区切ってテキストファイルへ書き出すツール。
Windows デスクトップでバックグラウンド動作させることを想定している。

- 出力ファイル名は **`YYYYMMDDhhmm-YYYYMMDDhhmm.txt`**（その1本がカバーする期間の開始と終了）
- 区切り幅・出力先・文字コードなどは **`config.toml`** で変更できる
- 追加ライブラリ不要（Python 3.11 以上の標準ライブラリのみ）

```
202609111400-202609111500.txt
202609111500-202609111600.txt
202609111600-202609111700.txt
```

## 必要なもの

- Python 3.11 以上（Windows は [python.org](https://www.python.org/downloads/windows/) の公式インストーラでよい。
  インストール時に *Add python.exe to PATH* にチェックを入れること）
- Whisper 系アプリが文字起こし結果を **フォルダに書き出す** 設定になっていること

対応する出力形式は `.txt` / `.json` / `.srt` / `.vtt`。
同じ音声から複数形式が出力される場合（`meeting.txt` と `meeting.srt` など）は、
同じ basename のものを1件にまとめるので二重計上にはならない。

## セットアップ

### 1. 取得元フォルダを確認する

Whisper の出力先が分かっていれば、まず中身を見てみる。

```bash
python -m withper_exporter probe "C:\Users\me\Documents\Whisper"
```

ファイル数・拡張子の内訳・更新時刻の範囲・本文の先頭が表示される。
ここで何も出ないなら、Whisper 側の出力先設定を先に確認する。

### 2. 設定ファイルを作る

```bash
python -m withper_exporter init --source-path "C:\Users\me\Documents\Whisper" --output-dir "C:\Users\me\Documents\WhisperExport"
```

`%APPDATA%\withper_exporter\config.toml`（Linux/macOS は `~/.config/withper_exporter/config.toml`）に雛形ができる。
`-c` を付ければ任意の場所に作れる。

### 3. 試し撃ちする

```bash
python -m withper_exporter run --dry-run
```

書き込まずに「どのファイルが何件で作られるか」だけを表示する。
問題なければ `--dry-run` を外して実行する。

```bash
python -m withper_exporter run
```

## バックグラウンドで動かす

### 方式A: タスクスケジューラ（推奨）

一定間隔で「1回だけ実行して終了」を繰り返す。常駐プロセスを抱えないので、
一度失敗しても次の実行で自動的に追いつく。PowerShell で以下を実行する。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -IntervalMinutes 10
```

- ログオン時に開始し、以後10分ごとに実行される
- `pythonw.exe` を使うのでコンソール画面は出ない
- 設定ファイルの場所を変えている場合は `-Config "C:\path\to\config.toml"` を付ける

| やること | コマンド |
| --- | --- |
| すぐ1回動かす | `Start-ScheduledTask -TaskName WithperExporter` |
| 実行状況を見る | `Get-ScheduledTaskInfo -TaskName WithperExporter` |
| 登録し直す | `install_task.ps1 -Force` |
| 解除する | `powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_task.ps1` |

> 実行間隔（`-IntervalMinutes`）と、ファイル1本の時間幅（`config.toml` の `interval`）は別物。
> 実行間隔のほうを短くしておけば、区切りが閉じた直後に書き出される。

### 方式B: 常駐プロセス

区切りが閉じるまで眠り、閉じたら書き出す常駐モード。

```bash
python -m withper_exporter daemon --flush-on-exit
```

画面を出さずに起動するなら `scripts\daemon_hidden.vbs` を実行する。
`Win+R` → `shell:startup` で開くフォルダにこの VBS のショートカットを置けば、ログオン時に自動起動する。

`Ctrl+C` や終了シグナルを受けると、`--flush-on-exit` 指定時は進行中の区切りも書き出してから終了する。

## 動きかた

### 区切り（ウィンドウ）の決まり方

`interval = "1h"`, `align = true` の場合、区切りは 14:00-15:00, 15:00-16:00 … と時刻の切りの良い位置に揃う。
レコードは **その時刻が属する区切り** に入る。境界ちょうど（15:00:00）は後ろ側の区切りに入る。

区切りが閉じてから `grace` だけ待って書き出す。Whisper がファイルを書いている最中に
拾ってしまうのを避けるための猶予で、既定は1分。

### 取りこぼしと重複の扱い

- どこまで処理したかは状態ファイル（既定 `%APPDATA%\withper_exporter\state.json`）に記録される
- PC を数時間落としていても、次の起動時に未処理の区切りをまとめて書き出す
- 同じ区切りを二度書き出すことはない（何度実行しても結果は変わらない）
- レコードが0件の区切りではファイルを作らない（`skip_empty = false` で変更可）

最初からやり直したいときは状態ファイルを削除する。`lookback` でさかのぼった分から作り直される。

## 設定リファレンス

### `[source]`

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `type` | `"whisperdir"` | 取得元の種類。`whisperdir` / `jsonl` / `json` / `sqlite` |
| `path` | （必須） | 取得元のフォルダまたはファイル |

### `[source.options]`（`whisperdir` の場合）

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `glob` | `"*"` | 対象ファイルの絞り込み |
| `recursive` | `false` | サブフォルダも見る |
| `timestamp_from` | `"mtime"` | 時刻の決め方。`mtime` / `ctime` / `filename` |
| `filename_regex` | — | `timestamp_from = "filename"` のとき、名前から時刻部分を取る正規表現（`(?P<ts>...)`） |
| `filename_format` | — | 取り出した文字列の書式（例 `"%Y%m%d_%H%M"`） |
| `suffixes` | `.txt .json .srt .vtt` 他 | 対象拡張子 |
| `dedupe_by_stem` | `true` | 同じ basename の複数形式を1件にまとめる |
| `prefer_suffixes` | `.txt .json .srt .vtt` | まとめるときに優先する形式の順 |
| `segments` | `false` | `.json`/`.srt`/`.vtt` をセグメント単位のレコードに展開する |
| `input_encoding` | `["utf-8-sig", "cp932"]` | 読み込み時に試す文字コード |

### `[export]`

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `output_dir` | `"export"` | 書き出し先フォルダ |
| `interval` | `"1h"` | ファイル1本の時間幅。`"10m"` / `"30m"` / `"1h"` / `"1d"`（**1分以上の分単位**） |
| `align` | `true` | 区切りを時刻の切りの良い位置に揃える |
| `lookback` | `"24h"` | 初回実行時にさかのぼる範囲 |
| `grace` | `"1m"` | 区切りが閉じてから書き出すまでの猶予 |
| `skip_empty` | `true` | 0件の区切りではファイルを作らない |
| `encoding` | `"utf-8-sig"` | 出力の文字コード（メモ帳向けには BOM 付きが無難） |
| `newline` | `"crlf"` | 改行コード。`crlf` / `lf` / `native` |
| `include_header` | `true` | 期間と件数のヘッダを先頭に付ける |
| `line_prefix_format` | `"[%H:%M:%S] "` | 各レコードの行頭に付ける時刻。`""` で無効 |
| `separator` | `""` | レコード間に追加で入れる区切り |
| `on_conflict` | `"overwrite"` | 同名ファイルがあるとき。`overwrite` / `append` / `skip` |
| `filename_suffix` | `".txt"` | 出力の拡張子 |
| `max_windows_per_run` | `500` | 1回の実行で処理する区切りの上限 |

`interval` が分単位に限られるのは、ファイル名 `YYYYMMDDhhmm` が分までしか表せないため。
秒単位にすると同名ファイルができてしまう。

### `[runtime]`

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `timezone` | `"local"` | `"Asia/Tokyo"` のような指定も可（Windows では `pip install tzdata` が必要） |
| `state_file` | アプリ設定フォルダ | 進捗の保存先 |
| `log_file` | アプリ設定フォルダ | ログの出力先。`false` で無効 |
| `log_level` | `"INFO"` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

## 出力例

```
# withper / Whisper 文字起こしエクスポート
# 期間: 2026-09-11 14:00 - 2026-09-11 15:00 (JST)
# 件数: 2
# 取得元: whisperdir(C:\Users\me\Documents\Whisper, glob=*)
[14:05:12] おはようございます。今日の議題は在庫管理の件です。
[14:32:40] 次の四半期の見通しについて共有します。
```

## 取得元を差し替える

Whisper アプリがフォルダではなく履歴ファイルやデータベースに記録する場合は `type` を変える。

```toml
# 1行1JSON のログ
[source]
type = "jsonl"
path = 'C:\Users\me\AppData\Roaming\SomeApp\history.jsonl'
[source.options]
timestamp_field = "created_at"   # "a.b.c" のようなドット区切りも可
text_field = "transcript"
```

```toml
# SQLite の履歴テーブル
[source]
type = "sqlite"
path = 'C:\Users\me\AppData\Roaming\SomeApp\history.db'
[source.options]
table = "transcripts"            # 代わりに query = "SELECT ..." も可
timestamp_field = "created_at"
text_field = "body"
```

時刻は ISO8601 / epoch秒 / epochミリ秒 / `YYYY-MM-DD HH:MM:SS` などを自動判別する。
判別できない書式は `timestamp_format`（strptime 書式）で明示する。

## 困ったとき

まず状態を確認する。

```bash
python -m withper_exporter status
```

| 症状 | 確認すること |
| --- | --- |
| ファイルが作られない | `status` の「取得元」が実在するか。`probe` でファイルが見えるか |
| 古い分が出てこない | 初回は `lookback`（既定24時間）より前は対象外。値を伸ばして状態ファイルを削除する |
| 直前の分が出てこない | `grace`（既定1分）の猶予待ち。次の実行で出る |
| 文字化けする | 出力側は `encoding`、読み込み側は `input_encoding` を調整する |
| `timezone` でエラー | Windows では `pip install tzdata`、または `"local"` を使う |
| タスクが動かない | `Get-ScheduledTaskInfo -TaskName WithperExporter` の `LastTaskResult` と、`log_file` のログを見る |

詳細ログは `-v` を付けるか `log_level = "DEBUG"` にする。

## 開発

```bash
python -m unittest discover -s tests -t .
```

動作確認用のサンプルデータを作る。

```bash
python sample_data/make_sample.py /tmp/whisper_out
```

### 構成

| パス | 役割 |
| --- | --- |
| `withper_exporter/cli.py` | コマンドライン |
| `withper_exporter/config.py` | `config.toml` の読み込みと検証 |
| `withper_exporter/exporter.py` | 区切りの決定・整形・書き込み |
| `withper_exporter/scheduler.py` | 常駐モードのループ |
| `withper_exporter/state.py` | どこまで処理したかの記録 |
| `withper_exporter/sources/` | 取得元アダプタ |
| `scripts/` | Windows 用の登録・起動スクリプト |
