"""Run `claude -p` non-interactively and parse its stream-json output."""
from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

TOOL_RESULT_CAP = 4000


@dataclass
class RunResult:
    text: str  # final assistant message (the report body)
    session_id: Optional[str]
    exit_code: int
    timed_out: bool
    stderr: str
    detail_md: str  # rendered process log (tool calls, intermediate text)


def build_command(cfg: dict, mode: str, prompt: str, session_id: Optional[str],
                  system_prompt_file: Optional[Path]) -> list[str]:
    bin_ = cfg["claude_bin"]
    cmd = list(bin_) if isinstance(bin_, (list, tuple)) else [bin_]
    cmd += ["-p", "--output-format", "stream-json", "--verbose"]
    cmd += list(cfg["execute_args"] if mode == "execute" else cfg["analyze_args"])
    if cfg.get("claude_model"):
        cmd += ["--model", cfg["claude_model"]]
    if session_id:
        cmd += ["--resume", session_id]
    elif system_prompt_file is not None:
        cmd += ["--append-system-prompt-file", str(system_prompt_file)]
    cmd.append(prompt)
    return cmd


def _fmt(x) -> str:
    if isinstance(x, str):
        return x
    return json.dumps(x, ensure_ascii=False, indent=2)


def parse_stream(lines: Iterable[str]) -> tuple[str, str, Optional[str]]:
    """Return (detail_md, final_text, session_id) from stream-json lines."""
    detail: list[str] = []
    final = ""
    sid: Optional[str] = None
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        t = ev.get("type")
        if t == "system" and ev.get("session_id"):
            sid = ev["session_id"]
        elif t == "assistant":
            for c in ev.get("message", {}).get("content", []) or []:
                if c.get("type") == "text":
                    detail.append(c.get("text", "") + "\n")
                elif c.get("type") == "tool_use":
                    detail.append(f"**→ {c.get('name')}**\n```json\n{_fmt(c.get('input', {}))}\n```\n")
        elif t == "user":
            for c in ev.get("message", {}).get("content", []) or []:
                if c.get("type") == "tool_result":
                    body = _fmt(c.get("content", ""))
                    if len(body) > TOOL_RESULT_CAP:
                        body = body[:TOOL_RESULT_CAP] + "\n…(truncated)"
                    detail.append(f"```\n{body}\n```\n")
        elif t == "result":
            final = ev.get("result") or ""
            sid = ev.get("session_id") or sid
    return "\n".join(detail), final, sid


def run_claude(cmd: list[str], cwd: Path, timeout_sec: float) -> RunResult:
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    out_lines: list[str] = []
    err_chunks: list[str] = []

    def pump(stream, sink):
        for line in stream:
            sink.append(line)

    t_out = threading.Thread(target=pump, args=(proc.stdout, out_lines), daemon=True)
    t_err = threading.Thread(target=pump, args=(proc.stderr, err_chunks), daemon=True)
    t_out.start()
    t_err.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait()
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    detail, final, sid = parse_stream(out_lines)
    code = proc.returncode if proc.returncode is not None else -1
    return RunResult(final, sid, code, timed_out, "".join(err_chunks), detail)
