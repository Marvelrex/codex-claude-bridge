"""Claude-side background loop: watch the notebook, run Claude, write reports."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

from bridge import runner as _runner
from bridge.notebook import DECISION_TAG, Entry, Notebook, truncate_body
from bridge.state import State

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
REQUIRED_TAGS = ("[What I did]", "[Result]", DECISION_TAG)
KIND_LABELS = {"directive": "directive", "note": "human note"}


def _flush_print(*args) -> None:
    print(*args, flush=True)


def detail_name(seq: int) -> str:
    return f"work/{seq:04d}-claude.md"


class Watcher:
    def __init__(self, project_dir: Path, cfg: dict, runner: Callable = _runner.run_claude,
                 sleep: Callable = time.sleep, log: Optional[Callable] = None):
        self.project_dir = Path(project_dir)
        self.bridge_dir = self.project_dir / ".bridge"
        self.cfg = cfg
        self.nb = Notebook(self.bridge_dir)
        self.state = State.load(self.bridge_dir)
        self.runner = runner
        self.sleep = sleep
        self.log = log if log is not None else _flush_print
        self._last_mtime = -1.0
        (self.bridge_dir / "work").mkdir(parents=True, exist_ok=True)

    # ---- prompt -------------------------------------------------------
    def build_prompt(self, entries: list[Entry], directive: Entry, first_round: bool) -> str:
        parts = []
        if first_round:
            parts.append(f"Project directory: {self.project_dir}\nNew entries from the shared notebook:")
        else:
            parts.append("New entries in the shared notebook:")
        for e in entries:
            tag = KIND_LABELS.get(e.kind, e.kind)
            mode = f" (mode: {e.mode})" if e.mode else ""
            parts.append(f"\n--- #{e.seq} {tag}{mode} from {e.from_} ---\n{e.body}")
        parts.append(
            f"\nThis round's mode = {directive.mode or 'analyze'}. Follow your role instructions. "
            f"Your final message must use the three-section format and stay under "
            f"{self.cfg['max_body_chars']} characters."
        )
        return "\n".join(parts)

    # ---- queue --------------------------------------------------------
    def pending(self) -> Optional[Entry]:
        for e in self.nb.since(self.state.last_processed):
            if e.kind == "directive" and e.to == "claude":
                return e
        return None

    def _system_prompt_file(self) -> Path:
        tpl = (TEMPLATES_DIR / "claude_system.md").read_text("utf-8")
        out = self.bridge_dir / "claude_system.rendered.md"
        out.write_text(tpl.replace("{MAX_BODY}", str(self.cfg["max_body_chars"])), "utf-8")
        return out

    def process(self, directive: Entry) -> Entry:
        mode = directive.mode or "analyze"
        context = [e for e in self.nb.since(self.state.last_processed) if e.seq <= directive.seq]
        first = self.state.session_id is None
        prompt = self.build_prompt(context, directive, first)
        sys_file = self._system_prompt_file() if first else None
        cmd = _runner.build_command(self.cfg, mode, prompt, self.state.session_id, sys_file)

        self.state.running_seq = directive.seq
        self.state.touch()
        self.state.save(self.bridge_dir)
        self.log(f"[bridge] #{directive.seq} → claude ({mode}) started")
        res = self._run_with_heartbeat(cmd)

        detail_rel = detail_name(directive.seq)
        detail_text = (
            f"# #{directive.seq} Claude process log (mode={mode})\n\n"
            f"## Directive\n\n{directive.body}\n\n## Process\n\n{res.detail_md}\n\n"
            f"## Final reply\n\n{res.text}\n"
        )
        (self.bridge_dir / detail_rel).write_text(detail_text, "utf-8")

        if res.timed_out:
            out = self.nb.append(
                "bridge", "codex", "system",
                f"Claude timed out after {self.cfg['claude_timeout_sec']}s and was terminated. "
                f"Partial process is in the detail file.",
                mode=mode, reply_to=directive.seq, detail=detail_rel, status="error")
        elif res.exit_code != 0 and not res.text:
            err = "\n".join(res.stderr.strip().splitlines()[:20]) or f"exit code {res.exit_code}"
            out = self.nb.append(
                "bridge", "codex", "system", f"Claude failed to run:\n{err}",
                mode=mode, reply_to=directive.seq, detail=detail_rel, status="error")
        else:
            text = res.text.strip() or "(Claude produced no output)"
            body, _cut = truncate_body(text, self.cfg["max_body_chars"])
            out = self.nb.append("claude", "codex", "report", body, mode=mode,
                                 reply_to=directive.seq, detail=detail_rel, status="done")
            if not all(t in res.text for t in REQUIRED_TAGS):
                self.nb.append("bridge", "human", "system",
                               f"Reply #{out.seq} does not follow the three-section format "
                               f"(or is empty). See the detail file.",
                               status="done")

        if res.session_id:
            self.state.session_id = res.session_id
        self.state.last_processed = directive.seq
        self.state.running_seq = None
        self.state.touch()
        self.state.save(self.bridge_dir)
        self.log(f"[bridge] #{directive.seq} finished → #{out.seq} ({out.status})\a")
        return out

    def _run_with_heartbeat(self, cmd: list[str]):
        """Run Claude while a side thread keeps state.heartbeat fresh, so `bridge wait`
        can tell 'Claude is busy' from 'watcher is dead' during long runs."""
        stop = threading.Event()
        interval = max(0.2, min(float(self.cfg["poll_interval_sec"]), self.cfg["heartbeat_stale_sec"] / 3))

        def beat():
            while not stop.wait(interval):
                self.state.touch()
                try:
                    self.state.save(self.bridge_dir)
                except OSError:
                    pass  # transient (e.g. reader holding the file); next beat retries

        t = threading.Thread(target=beat, daemon=True)
        t.start()
        try:
            return self.runner(cmd, self.project_dir, self.cfg["claude_timeout_sec"])
        finally:
            stop.set()
            t.join(timeout=5)

    def recover(self) -> None:
        rs = self.state.running_seq
        if rs is None:
            return
        if self.nb.find_reply(rs) is None:
            self.nb.append("bridge", "human", "system",
                           f"Watcher restarted: #{rs} did not finish last time and will be re-run.",
                           status="done")
        self.state.running_seq = None
        self.state.save(self.bridge_dir)

    def tick(self) -> bool:
        """One poll. Returns True if a directive was processed."""
        self.state.touch()
        self.state.save(self.bridge_dir)
        m = self.nb.mtime()
        if m == self._last_mtime:
            return False
        d = self.pending()
        if d is None:
            self._last_mtime = m
            return False
        self.process(d)
        return True

    def loop(self) -> None:
        self.recover()
        self.log(f"[bridge] watching {self.nb.path}  (Ctrl+C to stop)")
        try:
            while True:
                if not self.tick():
                    self.sleep(self.cfg["poll_interval_sec"])
        except KeyboardInterrupt:
            self.log("[bridge] stopped")
