import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from bridge import runner
from bridge.config import DEFAULTS

FAKE = [sys.executable, str(Path(__file__).parent / "fake_claude.py")]


class BuildCommandTest(unittest.TestCase):
    def test_analyze_first_round(self):
        cfg = dict(DEFAULTS, claude_bin="claude")
        cmd = runner.build_command(cfg, "analyze", "hi", None, Path("sys.md"))
        self.assertEqual(cmd[0], "claude")
        for flag in ("-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "plan"):
            self.assertIn(flag, cmd)
        self.assertIn("--append-system-prompt-file", cmd)
        self.assertNotIn("--resume", cmd)
        self.assertEqual(cmd[-1], "hi")

    def test_execute_resume_and_model(self):
        cfg = dict(DEFAULTS, claude_model="claude-opus-5")
        cmd = runner.build_command(cfg, "execute", "go", "sess-1", None)
        self.assertIn("acceptEdits", cmd)
        self.assertIn("Edit,Write,Bash", cmd)
        self.assertEqual(cmd[cmd.index("--resume") + 1], "sess-1")
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-opus-5")
        self.assertNotIn("--append-system-prompt-file", cmd)

    def test_claude_bin_may_be_list(self):
        cmd = runner.build_command(dict(DEFAULTS, claude_bin=FAKE), "analyze", "x", None, None)
        self.assertEqual(cmd[:2], FAKE)


class ParseStreamTest(unittest.TestCase):
    def test_parse(self):
        lines = [json.dumps(x) for x in [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "thinking"},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "a.py"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "print(1)"}]}},
            {"type": "result", "result": "FINAL", "session_id": "s1", "is_error": False},
        ]] + ["garbage line", ""]
        detail, final, sid = runner.parse_stream(lines)
        self.assertEqual((final, sid), ("FINAL", "s1"))
        for needle in ("thinking", "Read", "a.py", "print(1)"):
            self.assertIn(needle, detail)

    def test_parse_empty(self):
        self.assertEqual(runner.parse_stream([]), ("", "", None))


class RunClaudeTest(unittest.TestCase):
    def _with_mode(self, mode, fn):
        os.environ["FAKE_CLAUDE_MODE"] = mode
        try:
            return fn()
        finally:
            del os.environ["FAKE_CLAUDE_MODE"]

    def test_ok(self):
        with tempfile.TemporaryDirectory() as d:
            r = runner.run_claude(FAKE + ["-p", "x"], Path(d), 20)
            self.assertEqual(r.exit_code, 0)
            self.assertFalse(r.timed_out)
            self.assertEqual(r.session_id, "sess-123")
            self.assertIn("【做了什么】", r.text)
            self.assertIn("py -m unittest", r.detail_md)

    def test_timeout(self):
        def go():
            with tempfile.TemporaryDirectory() as d:
                r = runner.run_claude(FAKE, Path(d), 1.0)
                self.assertTrue(r.timed_out)
        self._with_mode("slow", go)

    def test_fail(self):
        def go():
            with tempfile.TemporaryDirectory() as d:
                r = runner.run_claude(FAKE, Path(d), 20)
                self.assertEqual(r.exit_code, 2)
                self.assertIn("Not logged in", r.stderr)
        self._with_mode("fail", go)
