"""Command-line entry point: bridge init | watch | send | wait | note | status | reset."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from bridge import __version__
from bridge.config import load_config, write_default_config
from bridge.notebook import Notebook
from bridge.state import State

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
START, END = "<!-- bridge:start -->", "<!-- bridge:end -->"
MODES = ("analyze", "execute")

# wait exit codes
WAIT_DONE, WAIT_NO_DIRECTIVE, WAIT_ERROR_REPLY, WAIT_NO_WATCHER, WAIT_TIMEOUT = 0, 1, 2, 3, 4


def resolve_project(arg) -> Path:
    return Path(arg).resolve() if arg else Path.cwd()


def bridge_dir_of(project: Path) -> Path:
    b = project / ".bridge"
    if not b.exists():
        print(f'错误：{project} 下没有 .bridge/，先运行：bridge init --project "{project}"')
        raise SystemExit(1)
    return b


def splice_agents_md(project: Path) -> None:
    """Insert or replace the bridge section in AGENTS.md, keeping other content."""
    snippet = (TEMPLATES_DIR / "AGENTS.snippet.md").read_text("utf-8").strip()
    p = project / "AGENTS.md"
    txt = p.read_text("utf-8") if p.exists() else ""
    if START in txt and END in txt:
        pre, rest = txt.split(START, 1)
        _, post = rest.split(END, 1)
        txt = pre + snippet + post
    else:
        txt = (txt.rstrip() + "\n\n" if txt.strip() else "") + snippet + "\n"
    p.write_text(txt, "utf-8")


# ---- subcommands -----------------------------------------------------------

def cmd_init(a) -> int:
    project = resolve_project(a.project)
    b = project / ".bridge"
    (b / "work").mkdir(parents=True, exist_ok=True)
    write_default_config(b)
    nb = Notebook(b)
    if not nb.path.exists():
        nb.path.touch()
    nb.render()
    splice_agents_md(project)
    print(f"已初始化 {b}")
    print("下一步：")
    print(f'  1) 另开一个终端常驻：bridge watch --project "{project}"')
    print(f"  2) 在 {project} 里启动 codex，正常对它说任务即可")
    return 0


def _append(a, from_: str, to: str, kind: str, mode) -> int:
    b = bridge_dir_of(resolve_project(a.project))
    e = Notebook(b).append(from_, to, kind, a.body, mode=mode)
    print(e.seq)
    return 0


def cmd_send(a) -> int:
    return _append(a, "codex", "claude", "directive", a.mode)


def cmd_note(a) -> int:
    return _append(a, "human", "claude", "note", None)


def cmd_status(a) -> int:
    b = bridge_dir_of(resolve_project(a.project))
    nb, cfg, st = Notebook(b), load_config(b), State.load(b)
    entries = nb.read_all()
    for e in entries[-a.n:] if a.n > 0 else entries:
        mode = f"[{e.mode}]" if e.mode else ""
        first = e.body.strip().splitlines()[0][:40] if e.body.strip() else ""
        print(f"#{e.seq} {e.ts[11:16]} {e.from_}→{e.to} {e.kind}{mode} {e.status}  {first}")
    age = st.heartbeat_age()
    alive = age < cfg["heartbeat_stale_sec"]
    age_s = f"{int(age)}s" if st.heartbeat else "从未"
    running = f"#{st.running_seq}" if st.running_seq else "-"
    print(f"watcher: {'alive' if alive else 'stale'} ({age_s})   claude running: {running}   "
          f"session: {st.session_id or '-'}")
    return 0


def cmd_reset(a) -> int:
    b = bridge_dir_of(resolve_project(a.project))
    st = State.load(b)
    st.session_id = None
    st.save(b)
    print("已清除 Claude session，下一轮从头开始（笔记本保留）。")
    return 0


def cmd_watch(a) -> int:
    from bridge.watcher import Watcher  # local import keeps CLI startup light

    project = resolve_project(a.project)
    b = bridge_dir_of(project)
    cfg = load_config(b)
    bin_ = cfg["claude_bin"]
    if isinstance(bin_, str):
        exe = shutil.which(bin_)
        if not exe:
            print(f"错误：找不到 {bin_}，请确认 Claude Code 已安装并在 PATH 中。")
            return 1
        try:
            subprocess.run([exe, "--version"], capture_output=True, timeout=60, check=True)
        except Exception as ex:  # noqa: BLE001 - report anything, then exit
            print(f"错误：claude --version 失败：{ex}")
            return 1
    Watcher(project, cfg).loop()
    return 0


def cmd_wait(a) -> int:
    b = bridge_dir_of(resolve_project(a.project))
    nb, cfg = Notebook(b), load_config(b)
    seq = a.seq
    if seq is None:
        ds = [e for e in nb.read_all() if e.kind == "directive" and e.to == "claude"]
        if not ds:
            print("没有可等待的指示，先 bridge send。")
            return WAIT_NO_DIRECTIVE
        seq = ds[-1].seq
    timeout = a.timeout if a.timeout is not None else cfg["claude_timeout_sec"] + 60
    start = last_dot = time.time()
    while True:
        r = nb.find_reply(seq)
        if r is not None:
            print(r.body)
            if r.detail:
                print(f"\n详情：.bridge/{r.detail}")
            return WAIT_DONE if r.status == "done" else WAIT_ERROR_REPLY
        st = State.load(b)
        if st.heartbeat_age() > cfg["heartbeat_stale_sec"]:
            age_s = f"{int(st.heartbeat_age())}s 无心跳" if st.heartbeat else "从未启动"
            print(f'watcher 未运行（{age_s}）。请让用户在另一个终端启动：bridge watch --project "{b.parent}"')
            return WAIT_NO_WATCHER
        if time.time() - start > timeout:
            print(f"等待 #{seq} 超过 {int(timeout)}s，放弃。稍后可用 bridge wait --seq {seq} 再等。")
            return WAIT_TIMEOUT
        if time.time() - last_dot >= 10:
            print(".", end="", file=sys.stderr, flush=True)
            last_dot = time.time()
        time.sleep(0.5)


# ---- parser -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bridge", description="Codex ↔ Claude 共享笔记本桥")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, help_, fn):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--project", help="项目目录（默认当前目录）")
        sp.set_defaults(fn=fn)
        return sp

    add("init", "初始化项目的 .bridge/ 并注入 AGENTS.md", cmd_init)
    add("watch", "Claude 侧后台监听（常驻）", cmd_watch)
    s = add("send", "Codex 给 Claude 下指示", cmd_send)
    s.add_argument("--mode", choices=MODES, default="analyze", help="analyze=只读，execute=可改文件跑命令")
    s.add_argument("body", help="指示内容")
    s = add("wait", "等待 Claude 的回复并打印", cmd_wait)
    s.add_argument("--seq", type=int, help="等待哪条指示的回复（默认最新一条）")
    s.add_argument("--timeout", type=float, default=None, help="秒；默认 = config.claude_timeout_sec + 60")
    s = add("note", "人工插话给 Claude", cmd_note)
    s.add_argument("body", help="备注内容")
    s = add("status", "最近几条摘要 + watcher 状态", cmd_status)
    s.add_argument("-n", type=int, default=5, help="显示最近 n 条，0 表示全部")
    add("reset", "清除 Claude session，下一轮从头开始", cmd_reset)
    return p


def main(argv=None) -> int:
    try:
        a = build_parser().parse_args(argv)
        return a.fn(a)
    except SystemExit as e:
        if e.code is None:
            return 0
        return e.code if isinstance(e.code, int) else 1
