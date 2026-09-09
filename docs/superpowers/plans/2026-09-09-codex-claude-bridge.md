# Codex ↔ Claude Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A zero-dependency Python CLI (`bridge`) that lets an interactive Codex session direct a background-driven Claude Code worker through a shared append-only JSONL notebook.

**Architecture:** `notebook.py` owns the JSONL log + Markdown render; `state.py` owns `state.json`; `runner.py` wraps `claude -p --output-format stream-json`; `watcher.py` polls the notebook and drives the runner; `cli.py` exposes `init/watch/send/wait/note/status/reset`. All modules are pure stdlib and tested with `unittest` using a fake `claude` script.

**Tech Stack:** Python 3.13 (via `py` launcher), stdlib only. Windows 11 primary target; shell shims for cmd and Git Bash.

**Spec:** `docs/superpowers/specs/2026-09-09-codex-claude-bridge-design.md`

## Global Constraints

- Python ≥ 3.12, standard library only. No pip dependencies.
- Run tests with `py -m unittest discover -s tests -v` from repo root.
- Notebook is append-only JSONL; one entry per line; readers skip malformed lines.
- `body` max length defaults to 400 chars (`max_body_chars`); the watcher truncates, never Claude.
- Directive `mode` ∈ {`analyze`, `execute`}; default `analyze`.
- Claude analyze args: `--permission-mode plan`. Execute args: `--permission-mode acceptEdits --allowedTools Edit,Write,Bash`.
- User-facing CLI text may be Chinese; code identifiers and log keys are English.
- Commit after every task.

---

## File Structure

```
bridge/__init__.py      # version string
bridge/__main__.py      # from bridge.cli import main; sys.exit(main())
bridge/config.py        # DEFAULTS, load_config, write_default_config
bridge/notebook.py      # Entry, Notebook, render_markdown, truncate_body
bridge/state.py         # State dataclass with load/save/touch/heartbeat_age
bridge/runner.py        # build_command, parse_stream, run_claude, RunResult
bridge/watcher.py       # Watcher: recover/tick/process/build_prompt/loop
bridge/cli.py           # argparse + subcommands
templates/AGENTS.snippet.md
templates/claude_system.md
tests/fake_claude.py    # prints canned stream-json; used by runner/watcher tests
tests/test_{config,notebook,state,runner,watcher,cli}.py
bridge.cmd              # Windows shim
bridge                  # Git Bash shim
README.md
scripts/smoke.md
```

---

### Task 1: Package skeleton + config

**Files:** Create `bridge/__init__.py`, `bridge/__main__.py`, `bridge/config.py`, stub `bridge/cli.py`; Test `tests/test_config.py`

**Interfaces:** `config.DEFAULTS: dict`, `config.load_config(bridge_dir: Path) -> dict` (merges config.json over DEFAULTS), `config.write_default_config(bridge_dir: Path) -> Path` (no overwrite).

DEFAULTS:
```python
{"max_body_chars": 400, "claude_timeout_sec": 1200, "poll_interval_sec": 1.0,
 "heartbeat_stale_sec": 30, "claude_bin": "claude",
 "analyze_args": ["--permission-mode", "plan"],
 "execute_args": ["--permission-mode", "acceptEdits", "--allowedTools", "Edit,Write,Bash"],
 "claude_model": None}
```

- [ ] Test: defaults when file missing; file overrides one key and keeps others; write_default_config creates file.
- [ ] Run → ImportError. Implement. Run → PASS. Commit `feat: package skeleton and config loader`.

---

### Task 2: Notebook (JSONL + Markdown render)

**Files:** Create `bridge/notebook.py`; Test `tests/test_notebook.py`

**Interfaces:**
- `Entry` dataclass: `seq:int, ts:str, from_:str, to:str, kind:str, mode:str|None, body:str, reply_to:int|None=None, detail:str|None=None, status:str="open"`; `to_json()` (key order seq,ts,from,to,kind,mode,body,reply_to,detail,status; `from_`↔`"from"`), `Entry.from_json(line)`.
- `truncate_body(text, limit) -> (str, bool)` appends `"\n…(已截断，全文见 detail)"` when cut.
- `render_markdown(entries) -> str`: `# Bridge Notebook`, then per entry `## #<seq> <from> → <to> · <kind> `<mode>` ↩ #<reply_to> · <status>`, italic ts, body, `详情：[detail](detail)`.
- `Notebook(bridge_dir)`: `.path` (notebook.jsonl), `.md_path`, `read_all()` (skip malformed lines), `next_seq()`, `append(from_, to, kind, body, mode=None, reply_to=None, detail=None, status="open") -> Entry` (open-append-write-flush, then `render()`), `since(seq)`, `find_reply(seq)` (first entry with `reply_to==seq` and kind in report/system), `mtime()`, `render()`.

- [ ] Tests: seq increments and `"from"` key on disk; malformed trailing line skipped and next_seq correct; since/find_reply incl. system error counting as reply; md written on append containing `## #1`, `codex → claude`, `` `execute` ``, detail link; truncate_body both branches.
- [ ] Run → fail. Implement. PASS. Commit `feat: JSONL notebook with markdown render`.

---

### Task 3: State

**Files:** Create `bridge/state.py`; Test `tests/test_state.py`

**Interfaces:** `@dataclass State(session_id=None, last_processed=0, running_seq=None, heartbeat=0.0)`; `State.load(bridge_dir)` (defaults on missing/corrupt), `save(bridge_dir)` (write tmp then replace), `touch()`, `heartbeat_age()`.

- [ ] Tests: roundtrip + defaults; corrupt file → defaults.
- [ ] Implement. PASS. Commit `feat: watcher state persistence`.

---

### Task 4: Runner (claude -p wrapper) + fake claude

**Files:** Create `bridge/runner.py`, `tests/fake_claude.py`; Test `tests/test_runner.py`

**fake_claude.py:** env `FAKE_CLAUDE_MODE` = ok|slow(sleep 30)|fail(stderr "Not logged in", exit 2); env `FAKE_CLAUDE_FINAL` overrides final text (default three-section string); env `FAKE_CLAUDE_ARGS_FILE` appends argv as JSON line. Emits events: system/init (session_id `sess-123`), assistant text+tool_use Bash `py -m unittest`, user tool_result "OK", result.

**Interfaces:**
- `RunResult(text, session_id, exit_code, timed_out, stderr, detail_md)`
- `build_command(cfg, mode, prompt, session_id, system_prompt_file) -> list[str]`: `claude_bin` (str or list) + `-p --output-format stream-json --verbose` + mode args + optional `--model` + (`--resume sid` if sid else `--append-system-prompt-file f` if f) + prompt last.
- `parse_stream(lines) -> (detail_md, final_text, session_id)`: handles system(init)/assistant(text, tool_use)/user(tool_result, cap 4000 chars)/result; skips garbage.
- `run_claude(cmd, cwd, timeout_sec) -> RunResult`: Popen with utf-8 pipes, stdout pumped on a thread, `wait(timeout)`, kill on timeout.

- [ ] Tests: analyze first round flags; execute+resume+model; list bin; parse_stream; run ok / timeout (1s) / fail.
- [ ] Implement. PASS. Commit `feat: claude runner with stream-json parsing`.

---

### Task 5: Templates

**Files:** `templates/claude_system.md` (role, two modes, boundaries, notes, no-directives rule, strict three-section final reply with `{MAX_BODY}` placeholder), `templates/AGENTS.snippet.md` (wrapped in `<!-- bridge:start -->`/`<!-- bridge:end -->`: Codex is lead, its usage is precious, delegate heavy work; how to `send --mode`, `wait`, `status`; only read `.bridge/work/NNNN-claude.md` when needed; never read notebook.jsonl in full; how to write good directives; if `wait` says watcher not running, tell the user).

- [ ] Write both. Commit `feat: role templates for claude and codex`.

---

### Task 6: Watcher

**Files:** Create `bridge/watcher.py`; Test `tests/test_watcher.py`

**Interfaces:**
- `TEMPLATES_DIR`, `REQUIRED_TAGS = ("【做了什么】","【结果/结论】","【待你决策】")`, `detail_name(seq) -> "work/NNNN-claude.md"`.
- `Watcher(project_dir, cfg, runner=run_claude, sleep=time.sleep, log=print)` with `.bridge_dir .nb .state`.
- `build_prompt(entries, directive, first_round)`: first round includes project path; lists each entry as `--- #seq 指示/人工备注(mode) 来自 X ---` + body; closes with mode and char limit reminder.
- `pending()`: first directive to claude with seq > last_processed.
- `process(directive)`: context = entries in (last_processed, directive.seq]; first round renders system template to `.bridge/claude_system.rendered.md`; sets running_seq, runs; writes detail file (header with directive, process, final reply); appends system(error) on timeout / nonzero-exit-with-empty-text (stderr first 20 lines), else report(done) with truncated body + system note to human if tags missing; updates session_id/last_processed/running_seq; logs with `\a`.
- `recover()`: if running_seq set and no reply → system note "will rerun"; clear running_seq.
- `tick()`: touch+save heartbeat; skip if mtime unchanged; process one pending (advance `_last_mtime` only when nothing pending).
- `loop()`: recover, then tick/sleep forever; KeyboardInterrupt exits.

- [ ] Tests: full round (report fields, detail file, state); prompt first vs resume; truncation + format warning; timeout system error; failure stderr; recover reruns.
- [ ] Implement. PASS. Commit `feat: watcher loop with recovery and error entries`.

---

### Task 7: CLI — init / send / note / status / reset / watch

**Files:** Replace `bridge/cli.py`; Test `tests/test_cli.py`

- `resolve_project(arg)`, `bridge_dir_of(project)` (SystemExit(1) with hint if missing).
- `splice_agents_md(project)`: idempotent replace between markers, else append (preserve existing content).
- `cmd_init`: mkdir `.bridge/work`, default config, touch notebook, render md, splice AGENTS, print next steps.
- `cmd_send` (codex→claude directive, `--mode` choices, default analyze, prints seq); `cmd_note` (human→claude note); `cmd_status -n` (one line per entry + watcher alive/stale + running + session); `cmd_reset` (session_id=None); `cmd_watch` (which+`--version` probe when claude_bin is str; then `Watcher.loop()`).
- `build_parser()` with `--project` on every subcommand; `wait` registered (stub until Task 8) with `--seq`, `--timeout`.
- `main(argv)` catches SystemExit → int.

- [ ] Tests: init layout + AGENTS idempotent; preserves existing AGENTS.md; send/note/status; default mode + bad mode rejected; reset; missing .bridge errors.
- [ ] Implement. PASS. Commit `feat: bridge CLI (init/send/note/status/reset/watch)`.

---

### Task 8: CLI — wait

- `cmd_wait`: target seq = arg or latest codex→claude directive (error 1 if none). timeout default = `claude_timeout_sec + 60`. Poll 0.5 s: reply found → print body (+ `详情：.bridge/<detail>`), return 0 (done) / 2 (error); heartbeat stale → print watcher-not-running hint, return 3; timeout → return 4; progress dot to stderr every 10 s.

- [ ] Tests: report arriving from a thread → 0 + body + detail; system error → 2; no heartbeat → 3; no directive → nonzero.
- [ ] Implement. Full suite PASS. Commit `feat: bridge wait`.

---

### Task 9: Shims, README, smoke script

- `bridge.cmd`: set PYTHONPATH to script dir, `py -3 -m bridge %*`.
- `bridge` (sh): same for Git Bash.
- `.gitignore`: `__pycache__/`, `*.pyc`, `.bridge/`.
- `README.md`: what, install (PATH), quick start, modes, notebook format, config keys, Codex sandbox approval note, wait exit codes, troubleshooting.
- `scripts/smoke.md`: real-run checklist (init → watch → analyze round → execute round creating a file → codex drives it → kill/restart watcher recovery).

- [ ] Write all, run suite, commit `docs: README, shims, smoke checklist`.

---

## Self-Review

- Spec coverage: layout (T1,T7,T9); message format (T2); config (T1); round flow with resume/system prompt (T4,T6); permission modes (T4); report format, truncation, format warning (T5,T6); errors — malformed line (T2), recovery (T6), claude probe (T7), heartbeat/wait codes (T8), timeout & stderr (T6); tests per module; smoke (T9); idempotent AGENTS splice (T7). No gaps.
- Placeholders: none.
- Type consistency: `Notebook.append` signature identical across T6/T7/T8; `build_command(cfg, mode, prompt, session_id, system_prompt_file)` in T4 and T6; `State` fields consistent.
