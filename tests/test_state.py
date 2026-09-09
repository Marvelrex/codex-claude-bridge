import tempfile
import unittest
from pathlib import Path

from bridge.state import State


class StateTest(unittest.TestCase):
    def test_roundtrip_and_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            s = State.load(Path(d))
            self.assertEqual(s.last_processed, 0)
            self.assertIsNone(s.session_id)
            s.session_id = "abc"
            s.last_processed = 3
            s.running_seq = 4
            s.touch()
            s.save(Path(d))
            s2 = State.load(Path(d))
            self.assertEqual((s2.session_id, s2.last_processed, s2.running_seq), ("abc", 3, 4))
            self.assertLess(s2.heartbeat_age(), 5)

    def test_corrupt_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "state.json").write_text("{not json", "utf-8")
            self.assertEqual(State.load(Path(d)).last_processed, 0)

    def test_never_touched_has_huge_age(self):
        self.assertGreater(State().heartbeat_age(), 1e6)
