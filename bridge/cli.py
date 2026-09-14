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
        print(f'Error: no .bridge/ under {project}. Run first: bridge init --project "{project}"')
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
    print(f"Initialised {b}")
    print("Next:")
    print(f'  1) In a separate terminal, keep this running: bridge watch --project "{project}"')
    print(f"  2) Start codex inside {project} and talk to it as usual")
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
    age_s = f"{int(age)}s" if st.heartbeat else "never"
    running = f"#{st.running_seq}" if st.running_seq else "-"
    print(f"watcher: {'alive' if alive else 'stale'} ({age_s})   claude running: {running}   "
          f"session: {st.session_id or '-'}")
    return 0


def cmd_reset(a) -> int:
    b = bridge_dir_of(resolve_project(a.project))
    st = State.load(b)
    st.session_id = None
    st.save(b)
    print("Claude session cleared. The next round starts fresh (notebook kept).")
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
            print(f"Error: {bin_} not found. Make sure Claude Code is installed and on PATH.")
            return 1
        try:
            subprocess.run([exe, "--version"], capture_output=True, timeout=60, check=True)
        except Exception as ex:  # noqa: BLE001 - report anything, then exit
            print(f"Error: claude --version failed: {ex}")
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
            print("Nothing to wait for. Run bridge send first.")
            return WAIT_NO_DIRECTIVE
        seq = ds[-1].seq
    timeout = a.timeout if a.timeout is not None else cfg["claude_timeout_sec"] + 60
    start = last_dot = time.time()
    while True:
        r = nb.find_reply(seq)
        if r is not None:
            print(r.body)
            if r.detail:
                print(f"\nDetail: .bridge/{r.detail}")
            return WAIT_DONE if r.status == "done" else WAIT_ERROR_REPLY
        st = State.load(b)
        if st.heartbeat_age() > cfg["heartbeat_stale_sec"]:
            age_s = f"no heartbeat for {int(st.heartbeat_age())}s" if st.heartbeat else "never started"
            print(f'The watcher is not running ({age_s}). Ask the user to start it in another terminal: '
                  f'bridge watch --project "{b.parent}"')
            return WAIT_NO_WATCHER
        if time.time() - start > timeout:
            print(f"Waited more than {int(timeout)}s for #{seq}. Run bridge wait --seq {seq} to keep waiting.")
            return WAIT_TIMEOUT
        if time.time() - last_dot >= 10:
            print(".", end="", file=sys.stderr, flush=True)
            last_dot = time.time()
        time.sleep(0.5)


# ---- parser -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bridge", description="Shared-notebook bridge between Codex and Claude")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, help_, fn):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--project", help="project directory (default: current directory)")
        sp.set_defaults(fn=fn)
        return sp

    add("init", "create .bridge/ in a project and inject the AGENTS.md section", cmd_init)
    add("watch", "run the Claude-side watcher (long-running)", cmd_watch)
    s = add("send", "Codex sends a directive to Claude", cmd_send)
    s.add_argument("--mode", choices=MODES, default="analyze",
                   help="analyze = read-only, execute = may edit files and run commands")
    s.add_argument("body", help="directive text")
    s = add("wait", "wait for Claude's reply and print it", cmd_wait)
    s.add_argument("--seq", type=int, help="directive seq to wait for (default: latest)")
    s.add_argument("--timeout", type=float, default=None,
                   help="seconds; default = config.claude_timeout_sec + 60")
    s = add("note", "human interjection for Claude", cmd_note)
    s.add_argument("body", help="note text")
    s = add("status", "digest of recent entries + watcher state", cmd_status)
    s.add_argument("-n", type=int, default=5, help="show the last n entries, 0 for all")
    add("reset", "clear Claude's session so the next round starts fresh", cmd_reset)
    return p


def main(argv=None) -> int:
    try:
        a = build_parser().parse_args(argv)
        return a.fn(a)
    except SystemExit as e:
        if e.code is None:
            return 0
        return e.code if isinstance(e.code, int) else 1
