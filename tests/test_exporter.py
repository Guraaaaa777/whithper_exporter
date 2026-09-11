import logging
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from withper_exporter.config import build_config
from withper_exporter.exporter import Exporter

from .helpers import base_config, dt, write_file


class ExporterTestBase(unittest.TestCase):
    def setUp(self):
        # 上限到達の警告などがテスト出力に混ざらないようにする
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.source_dir = root / "in"
        self.output_dir = root / "out"
        self.state_file = root / "state.json"
        self.source_dir.mkdir()

    def exporter(self, **export) -> Exporter:
        raw = base_config(self.source_dir, self.output_dir, self.state_file, **export)
        return Exporter(build_config(raw))

    def outputs(self) -> list[str]:
        if not self.output_dir.exists():
            return []
        return sorted(p.name for p in self.output_dir.iterdir())

    def read(self, name: str) -> str:
        return (self.output_dir / name).read_text(encoding="utf-8")


class WindowSlicingTest(ExporterTestBase):
    def test_records_land_in_their_hour(self):
        write_file(self.source_dir, "a.txt", "14時台の話", dt(hour=14, minute=5))
        write_file(self.source_dir, "b.txt", "15時台の話", dt(hour=15, minute=30))
        self.exporter().run_once(now=dt(hour=16, minute=10))
        self.assertEqual(
            self.outputs(),
            ["202609111400-202609111500.txt", "202609111500-202609111600.txt"],
        )
        self.assertIn("14時台の話", self.read("202609111400-202609111500.txt"))

    def test_boundary_belongs_to_later_window(self):
        write_file(self.source_dir, "a.txt", "ちょうど15時", dt(hour=15, minute=0))
        self.exporter().run_once(now=dt(hour=16, minute=10))
        self.assertEqual(self.outputs(), ["202609111500-202609111600.txt"])

    def test_ten_minute_interval(self):
        write_file(self.source_dir, "a.txt", "14:05の話", dt(hour=14, minute=5))
        self.exporter(interval="10m", lookback="1h").run_once(now=dt(hour=14, minute=30))
        self.assertEqual(self.outputs(), ["202609111400-202609111410.txt"])

    def test_daily_interval(self):
        write_file(self.source_dir, "a.txt", "昨日の話", dt(day=10, hour=14))
        self.exporter(interval="1d", lookback="3d").run_once(now=dt(day=11, hour=10))
        self.assertIn("202609100000-202609110000.txt", self.outputs())

    def test_unaligned_windows_chain_from_lookback(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=20))
        self.exporter(align=False, lookback="2h").run_once(now=dt(hour=15, minute=37))
        self.assertEqual(self.outputs(), ["202609111337-202609111437.txt"])


class IncrementalTest(ExporterTestBase):
    def test_second_run_is_a_noop(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=5))
        exporter = self.exporter()
        exporter.run_once(now=dt(hour=15, minute=10))
        before = self.outputs()
        result = exporter.run_once(now=dt(hour=15, minute=20))
        self.assertEqual(result.windows, [])
        self.assertEqual(self.outputs(), before)

    def test_catch_up_after_downtime(self):
        for hour in (14, 15, 16):
            write_file(self.source_dir, f"{hour}.txt", f"{hour}時台", dt(hour=hour, minute=5))
        exporter = self.exporter()
        exporter.run_once(now=dt(hour=15, minute=1))
        self.assertEqual(len(self.outputs()), 1)
        exporter.run_once(now=dt(hour=17, minute=1))
        self.assertEqual(len(self.outputs()), 3)

    def test_max_windows_per_run_caps_work(self):
        exporter = self.exporter(
            skip_empty=False, lookback="24h", max_windows_per_run=3
        )
        result = exporter.run_once(now=dt(hour=23))
        self.assertEqual(len(result.windows), 3)

    def test_state_survives_new_instance(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=5))
        self.exporter().run_once(now=dt(hour=15, minute=10))
        result = self.exporter().run_once(now=dt(hour=15, minute=20))
        self.assertEqual(result.windows, [])

    def test_corrupt_state_falls_back_to_lookback(self):
        self.state_file.write_text("{壊れている", encoding="utf-8")
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=5))
        self.exporter().run_once(now=dt(hour=15, minute=10))
        self.assertEqual(self.outputs(), ["202609111400-202609111500.txt"])


class GraceAndFlushTest(ExporterTestBase):
    def test_grace_delays_the_window(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=59))
        exporter = self.exporter(grace="5m")
        exporter.run_once(now=dt(hour=15, minute=2))
        self.assertEqual(self.outputs(), [])
        exporter.run_once(now=dt(hour=15, minute=6))
        self.assertEqual(self.outputs(), ["202609111400-202609111500.txt"])

    def test_flush_writes_partial_window(self):
        write_file(self.source_dir, "a.txt", "途中経過", dt(hour=15, minute=10))
        self.exporter().run_once(now=dt(hour=15, minute=30), flush=True)
        self.assertIn("202609111500-202609111530.txt", self.outputs())

    def test_flush_does_not_duplicate_on_next_run(self):
        write_file(self.source_dir, "a.txt", "途中経過", dt(hour=15, minute=10))
        exporter = self.exporter()
        exporter.run_once(now=dt(hour=15, minute=30), flush=True)
        exporter.run_once(now=dt(hour=16, minute=30))
        joined = "".join(self.read(name) for name in self.outputs())
        self.assertEqual(joined.count("途中経過"), 1)


class OutputFormatTest(ExporterTestBase):
    def test_records_are_sorted_and_prefixed(self):
        write_file(self.source_dir, "b.txt", "あと", dt(hour=14, minute=30))
        write_file(self.source_dir, "a.txt", "さき", dt(hour=14, minute=10))
        self.exporter().run_once(now=dt(hour=15, minute=10))
        body = self.read("202609111400-202609111500.txt")
        self.assertEqual(
            body, "[14:10:00] さき\n[14:30:00] あと\n"
        )

    def test_header_can_be_enabled(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=10))
        self.exporter(include_header=True).run_once(now=dt(hour=15, minute=10))
        body = self.read("202609111400-202609111500.txt")
        self.assertTrue(body.startswith("# withper"))
        self.assertIn("# 件数: 1", body)

    def test_prefix_can_be_disabled(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=10))
        self.exporter(line_prefix_format="").run_once(now=dt(hour=15, minute=10))
        self.assertEqual(self.read("202609111400-202609111500.txt"), "本文\n")

    def test_separator_inserts_blank_line(self):
        write_file(self.source_dir, "a.txt", "一件目", dt(hour=14, minute=10))
        write_file(self.source_dir, "b.txt", "二件目", dt(hour=14, minute=20))
        self.exporter(separator="\n").run_once(now=dt(hour=15, minute=10))
        self.assertIn("一件目\n\n[14:20:00]", self.read("202609111400-202609111500.txt"))

    def test_crlf_and_bom(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=10))
        self.exporter(newline="crlf", encoding="utf-8-sig").run_once(now=dt(hour=15))
        raw = (self.output_dir / "202609111400-202609111500.txt").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)

    def test_custom_suffix(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=10))
        self.exporter(filename_suffix=".log").run_once(now=dt(hour=15, minute=10))
        self.assertEqual(self.outputs(), ["202609111400-202609111500.log"])


class EmptyAndConflictTest(ExporterTestBase):
    def test_empty_window_skipped_by_default(self):
        result = self.exporter(lookback="2h").run_once(now=dt(hour=15, minute=10))
        self.assertEqual(self.outputs(), [])
        self.assertTrue(all(w.skipped_reason == "empty" for w in result.windows))

    def test_empty_window_written_when_requested(self):
        self.exporter(lookback="2h", skip_empty=False).run_once(now=dt(hour=15, minute=10))
        self.assertTrue(self.outputs())

    def test_overwrite_is_the_default(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=10))
        self.exporter().export_window(dt(hour=14), dt(hour=15))
        self.exporter().export_window(dt(hour=14), dt(hour=15))
        self.assertEqual(self.read("202609111400-202609111500.txt").count("本文"), 1)

    def test_append_mode(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=10))
        self.exporter(on_conflict="append").export_window(dt(hour=14), dt(hour=15))
        self.exporter(on_conflict="append").export_window(dt(hour=14), dt(hour=15))
        self.assertEqual(self.read("202609111400-202609111500.txt").count("本文"), 2)

    def test_skip_mode(self):
        write_file(self.source_dir, "a.txt", "最初", dt(hour=14, minute=10))
        self.exporter(on_conflict="skip").export_window(dt(hour=14), dt(hour=15))
        write_file(self.source_dir, "b.txt", "あとから", dt(hour=14, minute=20))
        result = self.exporter(on_conflict="skip").export_window(dt(hour=14), dt(hour=15))
        self.assertFalse(result.written)
        self.assertNotIn("あとから", self.read("202609111400-202609111500.txt"))

    def test_no_partial_file_left_behind(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=10))
        self.exporter().run_once(now=dt(hour=15, minute=10))
        self.assertEqual(
            [p.name for p in self.output_dir.glob("*.part")], []
        )


class DryRunTest(ExporterTestBase):
    def test_dry_run_writes_nothing_and_keeps_state(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14, minute=10))
        exporter = self.exporter()
        result = exporter.run_once(now=dt(hour=15, minute=10), dry_run=True)
        self.assertEqual(self.outputs(), [])
        self.assertEqual(result.windows[-1].record_count, 1)
        self.assertIsNone(exporter.state_store.load().last_window_end)


class DedupeTest(ExporterTestBase):
    def test_multi_format_output_from_one_audio_counted_once(self):
        """whisper は1つの音声から .txt/.srt/.json をまとめて吐くことがある。"""
        write_file(self.source_dir, "meeting.txt", "会議の本文", dt(hour=14, minute=10))
        write_file(
            self.source_dir,
            "meeting.srt",
            "1\n00:00:00,000 --> 00:00:02,000\n会議の本文\n",
            dt(hour=14, minute=10),
        )
        write_file(
            self.source_dir,
            "meeting.json",
            '{"text": "会議の本文"}',
            dt(hour=14, minute=10),
        )
        self.exporter().run_once(now=dt(hour=15, minute=10))
        body = self.read("202609111400-202609111500.txt")
        self.assertEqual(body.count("会議の本文"), 1)

    def test_stem_dedupe_can_be_disabled(self):
        write_file(self.source_dir, "meeting.txt", "本文A", dt(hour=14, minute=10))
        write_file(self.source_dir, "meeting.vtt", "WEBVTT\n\n本文B\n", dt(hour=14, minute=10))
        exporter = self.exporter()
        exporter.config.source.options["dedupe_by_stem"] = False
        exporter = Exporter(exporter.config)
        exporter.run_once(now=dt(hour=15, minute=10))
        body = self.read("202609111400-202609111500.txt")
        self.assertIn("本文A", body)
        self.assertIn("本文B", body)

    def test_identical_content_at_same_time_counted_once(self):
        write_file(self.source_dir, "a.txt", "重複", dt(hour=14, minute=10))
        write_file(self.source_dir, "copy_a.txt", "重複", dt(hour=14, minute=10))
        self.exporter().run_once(now=dt(hour=15, minute=10))
        self.assertEqual(self.read("202609111400-202609111500.txt").count("重複"), 1)


if __name__ == "__main__":
    unittest.main()
