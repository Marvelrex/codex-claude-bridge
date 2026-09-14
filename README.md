<div align="right">

**English** | [简体中文](README.zh-CN.md)

</div>

# codex-claude-bridge

**Let an interactive Codex CLI session lead a background Claude Code worker through a shared, append-only notebook.**

Codex spends tokens sparingly and only reads Claude's condensed reports. Claude does the heavy lifting (research, edits, tests) and keeps the long output out of Codex's context.

```
you ──chat──▶ codex (interactive terminal)
                │  bridge send / bridge wait
                ▼
        <project>/.bridge/notebook.jsonl   ◀── you can interject any time: bridge note
                ▲
                │  bridge watch (background, runs claude -p for you)
             claude
```

- **Zero dependencies**: Python 3.12+ standard library, one `bridge` command.
- **Append-only JSONL notebook**: two models can't corrupt each other's formatting; a rendered `notebook.md` is generated for humans.
- **Per-directive permissions**: `analyze` is read-only, `execute` may edit files and run commands.
- **Claude remembers across rounds**: sessions are resumed automatically, no re-feeding history.
- **Saves Codex tokens**: Claude's reply is capped to a short three-section summary; the full process is written to a side file that Codex reads only when needed.

## Requirements

- Windows 10/11 (primary test platform), Python 3.12+ via the `py` launcher
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI and [Codex CLI](https://github.com/openai/codex), both installed and logged in

## Install

```bat
git clone https://github.com/Marvelrex/codex-claude-bridge.git E:\codex-claude-bridge
```

Then make the `bridge` command available in every terminal, either way works:

1. **Add to PATH**: add the repo directory to your user PATH; cmd / PowerShell will pick up `bridge.cmd`.
   Note: an already-open Windows Terminal must be fully closed and reopened to see the new PATH.
2. **Drop a shim**: in any directory already on PATH (e.g. `%USERPROFILE%\.local\bin`) create `bridge.cmd`:
   ```bat
   @echo off
   setlocal
   set "PYTHONPATH=E:\codex-claude-bridge;%PYTHONPATH%"
   py -3 -m bridge %*
   ```

Git Bash users: `alias bridge='/e/codex-claude-bridge/bridge.sh'`

Verify: `bridge --version`

## Quick start

```bat
:: 1. Initialise the target project (creates .bridge/ and injects Codex instructions into AGENTS.md)
bridge init --project E:\MyProject

:: 2. Terminal A: start the Claude-side watcher and leave it running
bridge watch --project E:\MyProject

:: 3. Terminal B: start codex in the project as usual and just talk to it
cd E:\MyProject
codex
```

Once Codex reads `AGENTS.md` it will call `bridge send` to delegate work and `bridge wait` to collect the result on its own.
You can also tell Codex directly: "Have Claude do this, you just review the result." Codex may ask you to approve the first `bridge` command.

## The two modes

| mode | Claude flags | What Claude may do |
|---|---|---|
| `analyze` (default) | `--permission-mode plan` | Read-only: read files, search, browse, analyse |
| `execute` | `--permission-mode acceptEdits --allowedTools Edit,Write,Bash` | Edit files, run commands, run tests |

Codex picks the mode per directive: `bridge send --mode execute "..."`. You can narrow `execute_args` in `config.json`,
for example replace `Bash` with `Bash(git:*),Bash(py:*)`.

## Commands

| Command | Who | Purpose |
|---|---|---|
| `bridge init --project <dir>` | you | Create `.bridge/`, write default config, inject AGENTS.md section (idempotent) |
| `bridge watch --project <dir>` | you | Long-running Claude-side watcher |
| `bridge send [--mode analyze\|execute] "..."` | Codex | Append a directive, print its seq |
| `bridge wait [--seq N] [--timeout sec]` | Codex | Block until the reply arrives, print Claude's summary |
| `bridge note "..."` | you | Human interjection, fed to Claude on the next round |
| `bridge status [-n 5]` | you / Codex | One-line digest of the last n entries + watcher liveness |
| `bridge reset` | you | Clear Claude's session so the next round starts fresh (notebook kept) |

`send / wait / note / status / reset` default to the current directory as the project root when `--project` is omitted.

### `wait` exit codes

| Code | Meaning |
|---|---|
| 0 | Normal report received |
| 1 | No directive to wait for |
| 2 | Claude's round failed (timeout / process error); the body explains why |
| 3 | Watcher is not running (no heartbeat for `heartbeat_stale_sec`) |
| 4 | Exceeded `--timeout`; run `wait` again to keep waiting |

## Workspace layout

```
<project>/.bridge/
  notebook.jsonl      # single source of truth, one entry per line, append-only
  notebook.md         # re-rendered after every append, for humans
  state.json          # Claude session_id, last_processed, running_seq, heartbeat
  work/0003-claude.md # full process log of directive #3 (tool calls, reasoning, final reply)
  config.json         # see below
  claude_system.rendered.md  # role prompt injected into Claude on the first round
<project>/AGENTS.md   # contains a <!-- bridge:start --> … <!-- bridge:end --> section
```

Consider adding `.bridge/` to the target project's `.gitignore`.

### Message format

```json
{"seq": 3, "ts": "2026-09-09T01:20:00", "from": "codex", "to": "claude",
 "kind": "directive", "mode": "execute", "body": "...", "reply_to": null,
 "detail": null, "status": "open"}
```

- `kind`: `directive` (from Codex) / `report` (from Claude) / `note` (human) / `system` (framework event)
- `status`: `open` / `done` / `error`
- Claude's `report.body` always has three sections: *what I did / result / decisions for you*. Anything beyond
  `max_body_chars` is truncated by the watcher (the decision section is preserved first); the full text is always in the `detail` file.

### config.json

| Key | Default | Meaning |
|---|---|---|
| `max_body_chars` | 600 | Cap on Claude's summary length |
| `claude_timeout_sec` | 1200 | Max wall time for one Claude round |
| `poll_interval_sec` | 1.0 | Watcher poll interval |
| `heartbeat_stale_sec` | 30 | No heartbeat for this long means the watcher is considered dead |
| `claude_bin` | `"claude"` | Executable name or argument list |
| `analyze_args` / `execute_args` | see table above | Claude flags for the two modes |
| `claude_model` | null | Pass `--model`; null uses Claude Code's default |

## Design choices

- **One-directional**: only Codex → Claude directives and Claude → Codex reports. Claude never issues directives, so two models can't loop shouting at each other.
- **One Claude at a time**: directives queue up and run in order.
- **No web UI**: `notebook.md` is the interface.
- **Codex stays interactive**: Codex is never automated; you can step in at any point.

## Troubleshooting

- **`wait` returns 3**: the `bridge watch` terminal isn't running or was closed. Restart it; the watcher re-runs the interrupted directive automatically.
- **Claude keeps timing out**: raise `claude_timeout_sec`, or have Codex split the directive.
- **Claude's reply drifts from the format**: a `system` entry appears in the notebook; `bridge reset` clears the session so Claude re-reads its role prompt.
- **Want to see exactly what Claude did**: open `.bridge/work/NNNN-claude.md`.
- **Codex's own shell timeout interrupts `wait`**: the AGENTS instructions already tell Codex to use `--timeout 240` and rerun on exit code 4; if that's still not enough, raise Codex's shell tool timeout.

## Development

```bat
py -m unittest discover -s tests -v
```

Tests use a fake `claude` script (`tests/fake_claude.py`) that emits canned stream-json, so they cost no real usage.

- Design doc: `docs/superpowers/specs/2026-09-09-codex-claude-bridge-design.md`
- Implementation plan: `docs/superpowers/plans/2026-09-09-codex-claude-bridge.md`
- Real-machine smoke checklist: `scripts/smoke.md`

## Note on language

The CLI messages, the role prompt given to Claude and the AGENTS.md section injected for Codex are currently written in Chinese, since the tool was built for a Chinese-speaking workflow. The notebook format and all identifiers are language-neutral.

## License

MIT
