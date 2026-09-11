"""常駐モード（--daemon）のループ。"""

from __future__ import annotations

import logging
import signal
import threading
from datetime import datetime, timedelta

from .exporter import Exporter
from .sources import SourceError
from .timeutil import floor_to_interval

LOGGER = logging.getLogger(__name__)

#: ソース読み取りに失敗したときの待ち時間の上限
MAX_BACKOFF = timedelta(minutes=10)


class Daemon:
    """次のウィンドウが閉じるまで眠り、閉じたらエクスポートする。"""

    #: 取りこぼし防止のため、どんな場合でも最低限これだけは待つ（秒）
    DEFAULT_MIN_SLEEP = 5.0

    def __init__(
        self,
        exporter: Exporter,
        flush_on_exit: bool = False,
        min_sleep: float = DEFAULT_MIN_SLEEP,
    ) -> None:
        self.exporter = exporter
        self.flush_on_exit = flush_on_exit
        self.min_sleep = min_sleep
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            LOGGER.info("シグナル %s を受け取りました。終了します。", signum)
            self.request_stop()

        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):  # メインスレッド以外では設定できない
                pass

    def run(self) -> int:
        config = self.exporter.config
        LOGGER.info(
            "常駐モードを開始します (間隔=%s, 取得元=%s, 出力先=%s)",
            config.export.interval,
            self.exporter.source.describe(),
            config.export.output_dir,
        )
        failures = 0

        while not self._stop.is_set():
            try:
                result = self.exporter.run_once()
                failures = 0
                if result.written_files:
                    LOGGER.info(
                        "%d ファイル / %d 件を書き出しました",
                        result.written_files,
                        result.written_records,
                    )
            except SourceError as exc:
                failures += 1
                LOGGER.error("取得元エラー (%d回目): %s", failures, exc)
            except Exception:  # 常駐は落とさない
                failures += 1
                LOGGER.exception("予期しないエラー (%d回目)", failures)

            wait = self._sleep_seconds(failures)
            LOGGER.debug("次の実行まで %.0f 秒待機します", wait)
            if self._stop.wait(wait):
                break

        if self.flush_on_exit:
            LOGGER.info("終了前に未確定分を書き出します")
            try:
                self.exporter.run_once(flush=True)
            except Exception:
                LOGGER.exception("終了時のフラッシュに失敗しました")

        LOGGER.info("常駐モードを終了しました")
        return 0

    def _sleep_seconds(self, failures: int) -> float:
        config = self.exporter.config
        interval = config.export.interval
        now = datetime.now(tz=self.exporter.tz)

        if failures:
            backoff = min(interval * failures, MAX_BACKOFF)
            return max(backoff.total_seconds(), self.min_sleep)

        # 次にウィンドウが閉じる時刻（＋猶予）まで眠る
        next_boundary = floor_to_interval(now, interval) + interval + config.export.grace
        seconds = (next_boundary - now).total_seconds()
        # 境界ちょうどで起きて取りこぼさないよう、わずかに余裕を持たせる
        return max(seconds + 1.0, self.min_sleep)
