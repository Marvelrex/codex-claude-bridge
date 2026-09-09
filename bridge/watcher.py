"""Claude-side background loop: watch the notebook, run Claude, write reports."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from bridge import runner as _runner
from bridge.notebook import Entry, Notebook, truncate_body
from bridge.state import State

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
REQUIRED_TAGS = ("【做了什么】", "【结果/结论】", "【待你决策】")
KIND_LABELS = {"directive": "指示", "note": "人工备注"}


def detail_name(seq: int) -> str:
    return f"work/{seq:04d}-claude.md"


class Watcher:
    def __init__(self, project_dir: Path, cfg: dict, runner: Callable = _runner.run_claude,
                 sleep: Callable = time.sleep, log: Callable = print):
        self.project_dir = Path(project_dir)
        self.bridge_dir = self.project_dir / ".bridge"
        self.cfg = cfg
        self.nb = Notebook(self.bridge_dir)
        self.state = State.load(self.bridge_dir)
        self.runner = runner
        self.sleep = sleep
        self.log = log
        self._last_mtime = -1.0
        (self.bridge_dir / "work").mkdir(parents=True, exist_ok=True)

    # ---- prompt -------------------------------------------------------
    def build_prompt(self, entries: list[Entry], directive: Entry, first_round: bool) -> str:
        parts = []
        if first_round:
            parts.append(f"项目目录：{self.project_dir}\n以下是共享笔记本中的新条目。")
        else:
            parts.append("共享笔记本有新条目：")
        for e in entries:
            tag = KIND_LABELS.get(e.kind, e.kind)
            mode = f"（mode: {e.mode}）" if e.mode else ""
            parts.append(f"\n--- #{e.seq} {tag}{mode} 来自 {e.from_} ---\n{e.body}")
        parts.append(
            f"\n本轮 mode = {directive.mode or 'analyze'}。请按角色说明执行，"
            f"最后一段回复用三段式，不超过 {self.cfg['max_body_chars']} 字。"
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
        self.log(f"[bridge] #{directive.seq} → claude ({mode}) 开始")
        res = self.runner(cmd, self.project_dir, self.cfg["claude_timeout_sec"])

        detail_rel = detail_name(directive.seq)
        detail_text = (
            f"# #{directive.seq} Claude 过程记录（mode={mode}）\n\n"
            f"## 指示\n\n{directive.body}\n\n## 过程\n\n{res.detail_md}\n\n"
            f"## 最终回复\n\n{res.text}\n"
        )
        (self.bridge_dir / detail_rel).write_text(detail_text, "utf-8")

        if res.timed_out:
            out = self.nb.append(
                "bridge", "codex", "system",
                f"Claude 超时（{self.cfg['claude_timeout_sec']}s），已终止。部分过程见 detail。",
                mode=mode, reply_to=directive.seq, detail=detail_rel, status="error")
        elif res.exit_code != 0 and not res.text:
            err = "\n".join(res.stderr.strip().splitlines()[:20]) or f"exit code {res.exit_code}"
            out = self.nb.append(
                "bridge", "codex", "system", f"Claude 运行失败：\n{err}",
                mode=mode, reply_to=directive.seq, detail=detail_rel, status="error")
        else:
            text = res.text.strip() or "(Claude 没有输出)"
            body, _cut = truncate_body(text, self.cfg["max_body_chars"])
            out = self.nb.append("claude", "codex", "report", body, mode=mode,
                                 reply_to=directive.seq, detail=detail_rel, status="done")
            if not all(t in res.text for t in REQUIRED_TAGS):
                self.nb.append("bridge", "human", "system",
                               f"#{out.seq} 的回复不符合三段式格式（或为空），请查看 detail。",
                               status="done")

        if res.session_id:
            self.state.session_id = res.session_id
        self.state.last_processed = directive.seq
        self.state.running_seq = None
        self.state.touch()
        self.state.save(self.bridge_dir)
        self.log(f"[bridge] #{directive.seq} 完成 → #{out.seq} ({out.status})\a")
        return out

    def recover(self) -> None:
        rs = self.state.running_seq
        if rs is None:
            return
        if self.nb.find_reply(rs) is None:
            self.nb.append("bridge", "human", "system",
                           f"watcher 重启：#{rs} 上次未完成，将重跑。", status="done")
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
        self.log(f"[bridge] watching {self.nb.path}  (Ctrl+C 退出)")
        try:
            while True:
                if not self.tick():
                    self.sleep(self.cfg["poll_interval_sec"])
        except KeyboardInterrupt:
            self.log("[bridge] 已停止")
