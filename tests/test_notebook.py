import tempfile
import unittest
from pathlib import Path

from bridge.notebook import Entry, Notebook, render_markdown, truncate_body


class NotebookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.nb = Notebook(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_assigns_increasing_seq_and_writes_line(self):
        e1 = self.nb.append("codex", "claude", "directive", "do x", mode="execute")
        e2 = self.nb.append("claude", "codex", "report", "done", mode="execute", reply_to=1, status="done")
        self.assertEqual((e1.seq, e2.seq), (1, 2))
        lines = self.nb.path.read_text("utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(Entry.from_json(lines[0]).from_, "codex")
        self.assertIn('"from": "codex"', lines[0])

    def test_read_skips_malformed_last_line(self):
        self.nb.append("codex", "claude", "directive", "a")
        with open(self.nb.path, "a", encoding="utf-8") as f:
            f.write('{"seq": 2, "bro')
        self.assertEqual(len(self.nb.read_all()), 1)
        self.assertEqual(self.nb.next_seq(), 2)

    def test_since_and_find_reply(self):
        self.nb.append("codex", "claude", "directive", "a")
        self.nb.append("human", "claude", "note", "hint")
        r = self.nb.append("claude", "codex", "report", "ok", reply_to=1, status="done")
        self.assertEqual([e.seq for e in self.nb.since(1)], [2, 3])
        self.assertEqual(self.nb.find_reply(1).seq, r.seq)
        self.assertIsNone(self.nb.find_reply(2))

    def test_system_error_counts_as_reply(self):
        self.nb.append("codex", "claude", "directive", "a")
        self.nb.append("bridge", "codex", "system", "timeout", reply_to=1, status="error")
        self.assertEqual(self.nb.find_reply(1).kind, "system")

    def test_render_markdown_written_on_append(self):
        self.nb.append("codex", "claude", "directive", "fix tests", mode="execute")
        self.nb.append("claude", "codex", "report", "did it", mode="execute", reply_to=1,
                       detail="work/0001-claude.md", status="done")
        md = self.nb.md_path.read_text("utf-8")
        self.assertIn("## #1", md)
        self.assertIn("codex → claude", md)
        self.assertIn("`execute`", md)
        self.assertIn("[work/0001-claude.md](work/0001-claude.md)", md)

    def test_render_markdown_empty(self):
        self.assertIn("# Bridge Notebook", render_markdown([]))

    def test_truncate_body(self):
        s, cut = truncate_body("x" * 10, 5)
        self.assertTrue(cut)
        self.assertTrue(s.startswith("xxxxx"))
        self.assertIn("detail", s)
        s2, cut2 = truncate_body("short", 10)
        self.assertEqual((s2, cut2), ("short", False))
