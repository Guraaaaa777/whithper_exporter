"""動作確認用に、Whisper の出力フォルダを模したサンプルを作る。

    python sample_data/make_sample.py <出力先フォルダ>
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

SAMPLES = [
    ("14:05", "meeting_01.txt", "おはようございます。今日の議題は在庫管理の件です。"),
    ("14:32", "meeting_02.txt", "次の四半期の見通しについて共有します。"),
    ("15:10", "memo_01.txt", "買い物メモ。牛乳とコーヒー豆。"),
    ("15:48", "call_01.txt", "先方への折り返しは明日の午前中に行う。"),
    ("16:20", "daily.txt", "本日の作業ログをまとめました。"),
]


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "whisper_out")
    target.mkdir(parents=True, exist_ok=True)
    base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    for hhmm, name, text in SAMPLES:
        hour, minute = (int(part) for part in hhmm.split(":"))
        stamp = base.replace(hour=hour, minute=minute)
        path = target / name
        path.write_text(text + "\n", encoding="utf-8")
        os.utime(path, (stamp.timestamp(), stamp.timestamp()))

    # Whisper CLI の JSON 出力を模したもの
    json_path = target / "interview.json"
    json_path.write_text(
        json.dumps(
            {
                "text": "インタビュー全文です。",
                "segments": [
                    {"start": 0.0, "end": 3.2, "text": " まずは自己紹介をお願いします。"},
                    {"start": 3.2, "end": 8.0, "text": " 開発部の佐藤です。"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stamp = base.replace(hour=14, minute=50)
    os.utime(json_path, (stamp.timestamp(), stamp.timestamp()))

    # SRT 出力を模したもの
    srt_path = target / "lecture.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:04,500\n講義を始めます。\n\n"
        "2\n00:00:04,500 --> 00:00:09,000\n前回の復習からです。\n",
        encoding="utf-8",
    )
    stamp = base.replace(hour=16, minute=5)
    os.utime(srt_path, (stamp.timestamp(), stamp.timestamp()))

    print(f"サンプルを作成しました: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
