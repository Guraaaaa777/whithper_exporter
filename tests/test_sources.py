import json
import tempfile
import unittest
from pathlib import Path

from withper_exporter.sources import SourceError, build_source

from .helpers import TZ, dt, write_file


class WhisperDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def source(self, **options):
        return build_source("whisperdir", self.dir, options, TZ)

    def fetch(self, source, start=None, end=None):
        start = start or dt(hour=0)
        end = end or dt(hour=23, minute=59)
        return sorted(source.fetch(start, end), key=lambda r: (r.timestamp, r.text))

    def test_txt_uses_mtime(self):
        write_file(self.dir, "a.txt", "こんにちは\n", dt(hour=14, minute=5))
        records = self.fetch(self.source())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].text, "こんにちは")
        self.assertEqual(records[0].timestamp, dt(hour=14, minute=5))

    def test_blank_file_is_ignored(self):
        write_file(self.dir, "blank.txt", "   \n", dt(hour=14))
        self.assertEqual(self.fetch(self.source()), [])

    def test_unsupported_suffix_ignored(self):
        write_file(self.dir, "audio.wav", "not text", dt(hour=14))
        self.assertEqual(self.fetch(self.source()), [])

    def test_suffix_filter(self):
        write_file(self.dir, "a.txt", "テキスト", dt(hour=14))
        write_file(self.dir, "b.srt", "1\n00:00:00,000 --> 00:00:01,000\n字幕\n", dt(hour=14))
        records = self.fetch(self.source(suffixes=[".txt"]))
        self.assertEqual([r.text for r in records], ["テキスト"])

    def test_json_segments_joined_by_default(self):
        payload = {
            "text": "全文",
            "segments": [
                {"start": 0.0, "text": " 前半です。"},
                {"start": 5.0, "text": " 後半です。"},
            ],
        }
        write_file(self.dir, "a.json", json.dumps(payload, ensure_ascii=False), dt(hour=14))
        records = self.fetch(self.source())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].text, "前半です。\n後半です。")

    def test_json_segments_expanded(self):
        payload = {"segments": [{"start": 0.0, "text": "前半"}, {"start": 60.0, "text": "後半"}]}
        write_file(self.dir, "a.json", json.dumps(payload, ensure_ascii=False), dt(hour=14))
        records = self.fetch(self.source(segments=True))
        self.assertEqual([r.text for r in records], ["前半", "後半"])
        self.assertEqual(records[1].timestamp, dt(hour=14, minute=1))

    def test_json_without_segments_uses_text(self):
        write_file(self.dir, "a.json", json.dumps({"text": "本文だけ"}), dt(hour=14))
        self.assertEqual([r.text for r in self.fetch(self.source())], ["本文だけ"])

    def test_whisper_cpp_offsets(self):
        payload = {
            "transcription": [],
            "segments": [{"offsets": {"from": 90000}, "text": "90秒後"}],
        }
        write_file(self.dir, "a.json", json.dumps(payload, ensure_ascii=False), dt(hour=14))
        records = self.fetch(self.source(segments=True))
        self.assertEqual(records[0].timestamp, dt(hour=14, minute=1, second=30))

    def test_broken_json_raises(self):
        write_file(self.dir, "a.json", "{壊れている", dt(hour=14))
        with self.assertRaises(SourceError):
            self.fetch(self.source())

    def test_srt_strips_timecodes(self):
        srt = (
            "1\n00:00:00,000 --> 00:00:02,000\n最初の行\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n次の行\n"
        )
        write_file(self.dir, "a.srt", srt, dt(hour=14))
        records = self.fetch(self.source())
        self.assertEqual(records[0].text, "最初の行\n次の行")

    def test_vtt_header_is_dropped(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n字幕本文\n"
        write_file(self.dir, "a.vtt", vtt, dt(hour=14))
        self.assertEqual([r.text for r in self.fetch(self.source())], ["字幕本文"])

    def test_cp932_fallback(self):
        path = self.dir / "sjis.txt"
        path.write_bytes("日本語です".encode("cp932"))
        import os

        os.utime(path, (dt(hour=14).timestamp(),) * 2)
        self.assertEqual([r.text for r in self.fetch(self.source())], ["日本語です"])

    def test_timestamp_from_filename(self):
        write_file(self.dir, "20260911_1430_memo.txt", "本文", dt(hour=1))
        source = self.source(
            timestamp_from="filename",
            filename_regex=r"(?P<ts>\d{8}_\d{4})",
            filename_format="%Y%m%d_%H%M",
        )
        records = self.fetch(source)
        self.assertEqual(records[0].timestamp, dt(hour=14, minute=30))

    def test_unparsable_filename_skipped(self):
        write_file(self.dir, "名前だけ.txt", "本文", dt(hour=1))
        source = self.source(timestamp_from="filename")
        self.assertEqual(self.fetch(source), [])

    def test_recursive_option(self):
        write_file(self.dir / "sub", "a.txt", "入れ子", dt(hour=14))
        self.assertEqual(self.fetch(self.source()), [])
        self.assertEqual(len(self.fetch(self.source(recursive=True))), 1)

    def test_missing_path_raises(self):
        source = build_source("whisperdir", self.dir / "ない", {}, TZ)
        with self.assertRaises(SourceError):
            self.fetch(source)

    def test_ids_are_stable(self):
        write_file(self.dir, "a.txt", "同じ内容", dt(hour=14))
        first = self.fetch(self.source())[0].id
        second = self.fetch(self.source())[0].id
        self.assertEqual(first, second)


class JsonlTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_reads_lines(self):
        path = self.dir / "log.jsonl"
        path.write_text(
            '{"timestamp": "2026-09-11T14:05:00+09:00", "text": "一件目"}\n'
            "\n"
            '{"timestamp": "2026-09-11T14:06:00+09:00", "text": "二件目"}\n',
            encoding="utf-8",
        )
        source = build_source("jsonl", path, {}, TZ)
        records = sorted(source.fetch(dt(), dt(hour=23)), key=lambda r: r.timestamp)
        self.assertEqual([r.text for r in records], ["一件目", "二件目"])

    def test_custom_field_names_and_dotted_path(self):
        path = self.dir / "log.jsonl"
        path.write_text(
            '{"created": 1757567100, "result": {"body": "入れ子テキスト"}}\n',
            encoding="utf-8",
        )
        source = build_source(
            "jsonl",
            path,
            {"timestamp_field": "created", "text_field": "result.body"},
            TZ,
        )
        records = list(source.fetch(dt(), dt(hour=23)))
        self.assertEqual(records[0].text, "入れ子テキスト")

    def test_missing_field_reports_available_keys(self):
        path = self.dir / "log.jsonl"
        path.write_text('{"when": "2026-09-11T14:00:00", "body": "x"}\n', encoding="utf-8")
        source = build_source("jsonl", path, {}, TZ)
        with self.assertRaises(SourceError) as ctx:
            list(source.fetch(dt(), dt(hour=23)))
        self.assertIn("timestamp", str(ctx.exception))

    def test_broken_line_skipped_unless_strict(self):
        path = self.dir / "log.jsonl"
        path.write_text(
            '{"timestamp": "2026-09-11T14:00:00", "text": "有効"}\n壊れた行\n',
            encoding="utf-8",
        )
        lenient = build_source("jsonl", path, {}, TZ)
        self.assertEqual(len(list(lenient.fetch(dt(), dt(hour=23)))), 1)
        strict = build_source("jsonl", path, {"strict": True}, TZ)
        with self.assertRaises(SourceError):
            list(strict.fetch(dt(), dt(hour=23)))


class SqliteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_reads_table(self):
        import sqlite3

        db = self.dir / "history.db"
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE history (id INTEGER, created TEXT, body TEXT)")
            connection.execute(
                "INSERT INTO history VALUES (1, '2026-09-11 14:05:00', '文字起こし本文')"
            )
        source = build_source(
            "sqlite",
            db,
            {"table": "history", "timestamp_field": "created", "text_field": "body"},
            TZ,
        )
        records = list(source.fetch(dt(), dt(hour=23)))
        self.assertEqual(records[0].text, "文字起こし本文")
        self.assertEqual(records[0].timestamp, dt(hour=14, minute=5))

    def test_requires_table_or_query(self):
        import sqlite3

        db = self.dir / "history.db"
        sqlite3.connect(db).close()
        source = build_source("sqlite", db, {}, TZ)
        with self.assertRaises(SourceError):
            list(source.fetch(dt(), dt(hour=23)))


class RegistryTest(unittest.TestCase):
    def test_unknown_type(self):
        with self.assertRaises(SourceError):
            build_source("존재하지않음", None, {}, TZ)


if __name__ == "__main__":
    unittest.main()
