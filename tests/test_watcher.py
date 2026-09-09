import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from bridge.config import DEFAULTS
from bridge.state import State
from bridge.watcher import Watcher, detail_name

FAKE = [sys.executable, str(Path(__file__).parent / "fake_claude.py")]


def make(tmp, **over):
    proj = Path(tmp)
    (proj / ".bridge" / "work").mkdir(parents=True)
    cfg = {**DEFAULTS, "claude_bin": FAKE, "claude_timeout_sec": 20, **over}
    return proj, Watcher(proj, cfg, sleep=lambda s: None, log=lambda *a: None)


class EnvMixin:
    def with_env(self, key, value, fn):
        os.environ[key] = value
        try:
            return fn()
        finally:
            del os.environ[key]


class WatcherTest(EnvMixin, unittest.TestCase):
    def test_detail_name(self):
        self.assertEqual(detail_name(7), "work/0007-claude.md")

    def test_full_round(self):
        with tempfile.TemporaryDirectory() as d:
            proj, w = make(d)
            w.nb.append("codex", "claude", "directive", "run tests", mode="execute")
            self.assertTrue(w.tick())
            rep = w.nb.read_all()[-1]
            self.assertEqual((rep.kind, rep.reply_to, rep.status, rep.mode), ("report", 1, "done", "execute"))
            self.assertIn("【做了什么】", rep.body)
            self.assertEqual(rep.detail, "work/0001-claude.md")
            detail = (proj / ".bridge" / rep.detail).read_text("utf-8")
            self.assertIn("run tests", detail)
            self.assertIn("py -m unittest", detail)
            st = State.load(proj / ".bridge")
            self.assertEqual((st.session_id, st.last_processed, st.running_seq), ("sess-123", 1, None))
            self.assertFalse(w.tick())

    def test_passes_resume_on_second_round(self):
        with tempfile.TemporaryDirectory() as d:
            proj, w = make(d)
            args_file = proj / "args.jsonl"

            def go():
                w.nb.append("codex", "claude", "directive", "one")
                w.tick()
                w.nb.append("codex", "claude", "directive", "two")
                w.tick()
                lines = args_file.read_text("utf-8").splitlines()
                self.assertEqual(len(lines), 2)
                self.assertIn("--append-system-prompt-file", lines[0])
                self.assertNotIn("--resume", lines[0])
                self.assertIn("sess-123", lines[1])
                self.assertIn("--resume", lines[1])
            self.with_env("FAKE_CLAUDE_ARGS_FILE", str(args_file), go)

    def test_prompt_first_round_vs_resume(self):
        with tempfile.TemporaryDirectory() as d:
            proj, w = make(d)
            d1 = w.nb.append("codex", "claude", "directive", "A", mode="analyze")
            n = w.nb.append("human", "claude", "note", "hint")
            p = w.build_prompt([d1, n], d1, first_round=True)
            for needle in ("A", "hint", "analyze", str(proj), "人工备注"):
                self.assertIn(needle, p)
            p2 = w.build_prompt([d1], d1, first_round=False)
            self.assertNotIn(str(proj), p2)

    def test_truncation_and_system_note_on_bad_format(self):
        def go():
            with tempfile.TemporaryDirectory() as d:
                proj, w = make(d, max_body_chars=50)
                w.nb.append("codex", "claude", "directive", "x")
                w.tick()
                entries = w.nb.read_all()
                rep = [e for e in entries if e.kind == "report"][0]
                self.assertLess(len(rep.body), 120)
                self.assertIn("截断", rep.body)
                self.assertTrue(any(e.kind == "system" and "格式" in e.body for e in entries))
        self.with_env("FAKE_CLAUDE_FINAL", "y" * 1000, go)

    def test_timeout_writes_system_error(self):
        def go():
            with tempfile.TemporaryDirectory() as d:
                proj, w = make(d, claude_timeout_sec=1)
                w.nb.append("codex", "claude", "directive", "x")
                w.tick()
                last = w.nb.read_all()[-1]
                self.assertEqual((last.kind, last.status, last.reply_to), ("system", "error", 1))
                self.assertIn("超时", last.body)
                self.assertEqual(State.load(proj / ".bridge").last_processed, 1)
        self.with_env("FAKE_CLAUDE_MODE", "slow", go)

    def test_failure_writes_stderr(self):
        def go():
            with tempfile.TemporaryDirectory() as d:
                proj, w = make(d)
                w.nb.append("codex", "claude", "directive", "x")
                w.tick()
                last = w.nb.read_all()[-1]
                self.assertEqual(last.status, "error")
                self.assertIn("Not logged in", last.body)
        self.with_env("FAKE_CLAUDE_MODE", "fail", go)

    def test_recover_reruns_interrupted(self):
        with tempfile.TemporaryDirectory() as d:
            proj, w = make(d)
            w.nb.append("codex", "claude", "directive", "x")
            w.state.running_seq = 1
            w.state.save(w.bridge_dir)
            w.recover()
            self.assertIn("system", [e.kind for e in w.nb.read_all()])
            self.assertIsNone(w.state.running_seq)
            self.assertTrue(w.tick())

    def test_heartbeat_refreshed_while_claude_runs(self):
        with tempfile.TemporaryDirectory() as d:
            proj, w = make(d, poll_interval_sec=0.2, heartbeat_stale_sec=1)
            ages = []

            def slow_runner(cmd, cwd, timeout):
                time.sleep(1.5)
                ages.append(State.load(proj / ".bridge").heartbeat_age())
                from bridge.runner import RunResult
                return RunResult("【做了什么】a【结果/结论】b【待你决策】无", "s", 0, False, "", "")
            w.runner = slow_runner
            w.nb.append("codex", "claude", "directive", "x")
            w.tick()
            self.assertEqual(len(ages), 1)
            self.assertLess(ages[0], 1.0)

    def test_second_directive_appended_during_run_is_picked_up(self):
        with tempfile.TemporaryDirectory() as d:
            proj, w = make(d)
            w.nb.append("codex", "claude", "directive", "one")
            w.nb.append("codex", "claude", "directive", "two")
            self.assertTrue(w.tick())
            self.assertTrue(w.tick())
            self.assertFalse(w.tick())
            reports = [e for e in w.nb.read_all() if e.kind == "report"]
            self.assertEqual([r.reply_to for r in reports], [1, 2])
