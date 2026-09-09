import contextlib
import io
import tempfile
import threading
import time
import unittest
from pathlib import Path

from bridge import cli
from bridge.notebook import Notebook
from bridge.state import State


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(argv))
    return code, buf.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_creates_layout_and_agents_md_idempotent(self):
        code, out = run("init", "--project", str(self.proj))
        self.assertEqual(code, 0)
        b = self.proj / ".bridge"
        for p in ("config.json", "notebook.jsonl", "notebook.md", "work"):
            self.assertTrue((b / p).exists(), p)
        agents = (self.proj / "AGENTS.md").read_text("utf-8")
        self.assertIn("<!-- bridge:start -->", agents)
        self.assertIn("bridge send", agents)
        run("init", "--project", str(self.proj))
        self.assertEqual((self.proj / "AGENTS.md").read_text("utf-8").count("<!-- bridge:start -->"), 1)

    def test_init_preserves_existing_agents_md(self):
        (self.proj / "AGENTS.md").write_text("# Existing\nkeep me\n", "utf-8")
        run("init", "--project", str(self.proj))
        txt = (self.proj / "AGENTS.md").read_text("utf-8")
        self.assertTrue(txt.startswith("# Existing"))
        self.assertIn("keep me", txt)
        self.assertIn("bridge:start", txt)

    def test_send_note_status(self):
        run("init", "--project", str(self.proj))
        code, out = run("send", "--project", str(self.proj), "--mode", "execute", "fix it")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "1")
        run("note", "--project", str(self.proj), "careful")
        es = Notebook(self.proj / ".bridge").read_all()
        self.assertEqual([e.kind for e in es], ["directive", "note"])
        self.assertEqual(es[0].mode, "execute")
        self.assertEqual(es[1].from_, "human")
        code, out = run("status", "--project", str(self.proj), "-n", "5")
        self.assertIn("#1", out)
        self.assertIn("directive", out)
        self.assertIn("watcher", out)

    def test_send_default_mode_analyze_and_rejects_bad_mode(self):
        run("init", "--project", str(self.proj))
        run("send", "--project", str(self.proj), "hello")
        self.assertEqual(Notebook(self.proj / ".bridge").read_all()[0].mode, "analyze")
        code, out = run("send", "--project", str(self.proj), "--mode", "yolo", "x")
        self.assertNotEqual(code, 0)

    def test_reset_clears_session(self):
        run("init", "--project", str(self.proj))
        State(session_id="s").save(self.proj / ".bridge")
        run("reset", "--project", str(self.proj))
        self.assertIsNone(State.load(self.proj / ".bridge").session_id)

    def test_missing_bridge_dir_errors(self):
        code, out = run("send", "--project", str(self.proj), "x")
        self.assertNotEqual(code, 0)
        self.assertIn("bridge init", out)


class WaitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name)
        run("init", "--project", str(self.proj))
        self.b = self.proj / ".bridge"

    def tearDown(self):
        self.tmp.cleanup()

    def _alive(self):
        st = State.load(self.b)
        st.touch()
        st.save(self.b)

    def test_wait_returns_body_when_report_arrives(self):
        run("send", "--project", str(self.proj), "do")
        self._alive()

        def later():
            time.sleep(0.7)
            Notebook(self.b).append("claude", "codex", "report", "【做了什么】x", reply_to=1,
                                    detail="work/0001-claude.md", status="done")
        t = threading.Thread(target=later)
        t.start()
        code, out = run("wait", "--project", str(self.proj), "--timeout", "10")
        t.join()
        self.assertEqual(code, 0)
        self.assertIn("【做了什么】x", out)
        self.assertIn("work/0001-claude.md", out)

    def test_wait_error_reply_exit_2(self):
        run("send", "--project", str(self.proj), "do")
        self._alive()
        Notebook(self.b).append("bridge", "codex", "system", "超时", reply_to=1, status="error")
        code, out = run("wait", "--project", str(self.proj))
        self.assertEqual(code, 2)
        self.assertIn("超时", out)

    def test_wait_specific_seq(self):
        run("send", "--project", str(self.proj), "one")
        run("send", "--project", str(self.proj), "two")
        self._alive()
        Notebook(self.b).append("claude", "codex", "report", "first", reply_to=1, status="done")
        code, out = run("wait", "--project", str(self.proj), "--seq", "1")
        self.assertEqual(code, 0)
        self.assertIn("first", out)

    def test_wait_no_watcher_exit_3(self):
        run("send", "--project", str(self.proj), "do")
        code, out = run("wait", "--project", str(self.proj), "--timeout", "10")
        self.assertEqual(code, 3)
        self.assertIn("watcher", out)

    def test_wait_without_directive_errors(self):
        code, out = run("wait", "--project", str(self.proj))
        self.assertNotEqual(code, 0)
