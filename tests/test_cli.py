import contextlib
import io
import logging
import tempfile
import unittest
from pathlib import Path

from withper_exporter.cli import main

from .helpers import dt, write_file


class CliTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = self.root / "config.toml"
        self.source_dir = self.root / "in"
        self.output_dir = self.root / "out"
        self.source_dir.mkdir()

    def run_cli(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def init(self, *extra):
        result = self.run_cli(
            "init",
            "-c",
            str(self.config),
            "--source-path",
            str(self.source_dir),
            "--output-dir",
            str(self.output_dir),
            *extra,
        )
        if self.config.exists():
            self._isolate_runtime_paths()
        return result

    def _isolate_runtime_paths(self):
        """状態ファイルとログは既定でユーザ設定フォルダを指すので、テスト用に閉じ込める。"""
        text = self.config.read_text(encoding="utf-8")
        if "# テスト用" in text:
            return
        self.config.write_text(
            text + f'\n# テスト用\nstate_file = "{(self.root / "state.json").as_posix()}"\n'
            "log_file = false\n",
            encoding="utf-8",
        )

    def test_init_creates_usable_config(self):
        code, out, _ = self.init()
        self.assertEqual(code, 0)
        self.assertTrue(self.config.exists())
        self.assertIn("設定ファイルを作成しました", out)

    def test_init_refuses_to_clobber(self):
        self.init()
        code, _, err = self.init()
        self.assertEqual(code, 1)
        self.assertIn("--force", err)
        self.assertEqual(self.init("--force")[0], 0)

    def test_run_without_config_is_a_clear_error(self):
        code, _, err = self.run_cli("run", "-c", str(self.root / "ない.toml"))
        self.assertEqual(code, 2)
        self.assertIn("設定エラー", err)

    def test_run_exports_and_is_idempotent(self):
        self.init()
        write_file(self.source_dir, "a.txt", "本文です", dt(hour=14, minute=10))
        code, out, _ = self.run_cli("run", "-c", str(self.config), "--quiet")
        self.assertEqual(code, 0)
        exported = sorted(p.name for p in self.output_dir.iterdir())
        self.assertTrue(exported)
        self.assertRegex(exported[0], r"^\d{12}-\d{12}\.txt$")

        code, out, _ = self.run_cli("run", "-c", str(self.config), "--quiet")
        self.assertIn("ウィンドウはまだありません", out)

    def test_dry_run_leaves_no_files(self):
        self.init()
        write_file(self.source_dir, "a.txt", "本文です", dt(hour=14, minute=10))
        code, out, _ = self.run_cli("run", "-c", str(self.config), "--dry-run", "--quiet")
        self.assertEqual(code, 0)
        self.assertIn("--dry-run", out)
        self.assertFalse(self.output_dir.exists() and list(self.output_dir.iterdir()))

    def test_global_flags_work_before_and_after_subcommand(self):
        self.init()
        self.assertEqual(self.run_cli("-c", str(self.config), "status")[0], 0)
        self.assertEqual(self.run_cli("status", "-c", str(self.config))[0], 0)

    def test_status_reports_settings(self):
        self.init()
        code, out, _ = self.run_cli("status", "-c", str(self.config))
        self.assertEqual(code, 0)
        self.assertIn("出力先", out)
        self.assertIn("間隔", out)

    def test_probe_on_missing_path(self):
        code, out, _ = self.run_cli("probe", str(self.root / "ない"))
        self.assertEqual(code, 0)
        self.assertIn("見つかりません", out)

    def test_probe_reports_files(self):
        write_file(self.source_dir, "a.txt", "本文", dt(hour=14))
        code, out, _ = self.run_cli("probe", str(self.source_dir))
        self.assertEqual(code, 0)
        self.assertIn("whisperdir で拾える数: 1", out)


if __name__ == "__main__":
    unittest.main()
