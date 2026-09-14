<!-- bridge:start -->
## Bridge: you have a worker named Claude

You are the lead on this project. A worker, Claude, is on call through the command line. It is good at deep research and heavy execution, and its usage is not a concern.
**Your usage is scarce**: anything that means reading many files, running tests, looking things up, writing long code or iterating through trial and error goes to Claude. You decide and review.

### How to use it
- Delegate: `bridge send --mode analyze "directive"` or `bridge send --mode execute "directive"`. The command prints a seq number.
  - `analyze`: Claude is read-only. Use for research, analysis, review.
  - `execute`: Claude may edit files and run commands. Use for implementation, bug fixes, running tests.
- Collect the result: `bridge wait --timeout 240` (waits for the reply to the latest directive by default). The text it prints is Claude's summary, always in three sections:
  [What I did] [Result] [Decisions for you]. Decide directly from it.
  - A Claude round usually takes 1 to 10 minutes. Set your shell tool timeout to at least 300 seconds when running `wait`.
  - Exit code 4 means not finished yet: run `bridge wait --timeout 240` again. Exit code 2 means Claude's round failed; the body says why.
- Review: `bridge status -n 5` shows a one-line digest of recent entries and whether Claude is running.
- Read `.bridge/work/NNNN-claude.md` for the full process only when the summary is not enough. Do not read it routinely, and do not read `.bridge/notebook.jsonl` in full.

### Writing good directives
- State the goal, the boundaries (files or interfaces that must not change) and the form of output you want.
- One directive does one thing. Split large tasks into several directives, `send` then `wait` for each.
- When Claude should investigate before acting, send an `analyze` directive first, read the conclusion, then send `execute`.
- If `wait` reports that the watcher is not running, tell the user to start `bridge watch` in another terminal. Do not retry on your own.
<!-- bridge:end -->
