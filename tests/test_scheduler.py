import logging
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from withper_exporter.scheduler import MAX_BACKOFF, Daemon
from withper_exporter.sources import SourceError

from .helpers import TZ


class FakeExporter:
    """Daemon の制御フローだけを見るためのスタブ。"""

    def __init__(self, interval=timedelta(hours=1), grace=timedelta(0), errors=0):
        self.calls: list[dict] = []
        self.errors = errors
        self.tz = TZ
        self.source = SimpleNamespace(describe=lambda: "fake")
        self.config = SimpleNamespace(
            export=SimpleNamespace(
                interval=interval,
                grace=grace,
                output_dir="out",
            )
        )

    def run_once(self, **kwargs):
        self.calls.append(kwargs)
        if self.errors > 0:
            self.errors -= 1
            raise SourceError("取得元が読めません")
        return SimpleNamespace(written_files=0, written_records=0)


class DaemonTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def test_stops_on_request(self):
        exporter = FakeExporter()
        daemon = Daemon(exporter, min_sleep=0.01)
        original = exporter.run_once

        def run_then_stop(**kwargs):
            result = original(**kwargs)
            daemon.request_stop()
            return result

        exporter.run_once = run_then_stop
        self.assertEqual(daemon.run(), 0)
        self.assertEqual(len(exporter.calls), 1)

    def test_flush_on_exit(self):
        exporter = FakeExporter()
        daemon = Daemon(exporter, flush_on_exit=True, min_sleep=0.01)
        original = exporter.run_once

        def run_then_stop(**kwargs):
            result = original(**kwargs)
            daemon.request_stop()
            return result

        exporter.run_once = run_then_stop
        daemon.run()
        self.assertEqual(exporter.calls[-1], {"flush": True})

    def test_source_errors_do_not_kill_the_loop(self):
        exporter = FakeExporter(interval=timedelta(seconds=1), errors=1)
        daemon = Daemon(exporter, min_sleep=0.01)
        calls = {"n": 0}
        original = exporter.run_once

        def counted(**kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                daemon.request_stop()
            return original(**kwargs)

        exporter.run_once = counted
        # 1回目は失敗するがループは続き、2回目で停止する
        self.assertEqual(daemon.run(), 0)
        self.assertEqual(calls["n"], 2)

    def test_sleeps_until_the_next_boundary(self):
        exporter = FakeExporter()
        daemon = Daemon(exporter, min_sleep=0.01)
        # 実時刻に依存しないよう、境界計算そのものを確かめる
        seconds = daemon._sleep_seconds(failures=0)
        self.assertGreater(seconds, 0)
        self.assertLessEqual(seconds, timedelta(hours=1).total_seconds() + 1)

    def test_backoff_grows_and_is_capped(self):
        exporter = FakeExporter()
        daemon = Daemon(exporter, min_sleep=0.01)
        first = daemon._sleep_seconds(failures=1)
        many = daemon._sleep_seconds(failures=100)
        self.assertGreaterEqual(many, first)
        self.assertLessEqual(many, MAX_BACKOFF.total_seconds())


if __name__ == "__main__":
    unittest.main()
