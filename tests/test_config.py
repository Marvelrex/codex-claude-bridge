import json
import tempfile
import unittest
from pathlib import Path

from bridge import config


class ConfigTest(unittest.TestCase):
    def test_defaults_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = config.load_config(Path(d))
            self.assertEqual(cfg["max_body_chars"], 600)
            self.assertEqual(cfg["analyze_args"], ["--permission-mode", "plan"])

    def test_file_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.json").write_text(json.dumps({"max_body_chars": 100}), "utf-8")
            cfg = config.load_config(Path(d))
            self.assertEqual(cfg["max_body_chars"], 100)
            self.assertEqual(cfg["claude_timeout_sec"], 1200)

    def test_write_default_config(self):
        with tempfile.TemporaryDirectory() as d:
            p = config.write_default_config(Path(d))
            self.assertTrue(p.exists())
            self.assertEqual(json.loads(p.read_text("utf-8"))["poll_interval_sec"], 1.0)
