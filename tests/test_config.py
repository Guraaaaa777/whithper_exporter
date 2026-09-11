import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from withper_exporter.config import ConfigError, build_config, load_config
from withper_exporter.template import render_template


class BuildConfigTest(unittest.TestCase):
    def test_defaults(self):
        config = build_config({})
        self.assertEqual(config.source.type, "whisperdir")
        self.assertEqual(config.export.interval, timedelta(hours=1))
        self.assertEqual(config.export.newline_chars, "\r\n")

    def test_interval_forms(self):
        self.assertEqual(
            build_config({"export": {"interval": "10m"}}).export.interval,
            timedelta(minutes=10),
        )
        self.assertEqual(
            build_config({"export": {"interval": 1800}}).export.interval,
            timedelta(minutes=30),
        )

    def test_relative_paths_resolve_against_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config = build_config({"export": {"output_dir": "out"}}, config_path)
            self.assertEqual(config.export.output_dir, Path(tmp).resolve() / "out")

    def test_log_file_false_disables_logging(self):
        config = build_config({"runtime": {"log_file": False}})
        self.assertIsNone(config.runtime.log_file)

    def test_invalid_values_are_rejected(self):
        cases = [
            {"source": {"type": "なにこれ"}},
            {"export": {"newline": "cr"}},
            {"export": {"on_conflict": "merge"}},
            {"export": {"interval": "1x"}},
            {"export": {"max_windows_per_run": 0}},
            {"export": {"interval": "30s"}},
            {"export": {"interval": "90s"}},
            {"export": {"encoding": "utf-99"}},
            {"runtime": {"timezone": "Mars/Olympus"}},
        ]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ConfigError):
                build_config(raw)

    def test_interval_must_be_whole_minutes(self):
        """ファイル名が分単位なので、秒単位の区切りは名前が衝突してしまう。"""
        with self.assertRaises(ConfigError) as ctx:
            build_config({"export": {"interval": "45s"}})
        self.assertIn("分単位", str(ctx.exception))
        self.assertEqual(
            build_config({"export": {"interval": "5m"}}).export.interval,
            timedelta(minutes=5),
        )

    def test_section_must_be_a_table(self):
        with self.assertRaises(ConfigError):
            build_config({"export": "1h"})


class LoadConfigTest(unittest.TestCase):
    def test_template_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(render_template(Path(tmp) / "in", Path(tmp) / "out"), "utf-8")
            config = load_config(path)
            self.assertEqual(config.source.path, Path(tmp) / "in")
            self.assertEqual(config.export.output_dir, Path(tmp) / "out")
            self.assertEqual(config.export.grace, timedelta(minutes=1))

    def test_windows_style_path_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                render_template(Path(r"C:\Users\me\Documents\Whisper"), Path(tmp) / "out"),
                "utf-8",
            )
            config = load_config(path)
            self.assertIn("Whisper", str(config.source.path))
            self.assertNotIn("\\\\", str(config.source.path))

    def test_missing_file_explains_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as ctx:
                load_config(Path(tmp) / "ない.toml")
            self.assertIn("init", str(ctx.exception))

    def test_syntax_error_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("[export\ninterval =", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
