"""Fake `claude` CLI for tests.

Controlled by environment variables:
  FAKE_CLAUDE_MODE       ok (default) | slow (sleep 30s) | fail (stderr + exit 2)
  FAKE_CLAUDE_FINAL      override the final result text
  FAKE_CLAUDE_ARGS_FILE  if set, append argv (JSON) to this file
"""
import json
import os
import sys
import time

if os.environ.get("FAKE_CLAUDE_ARGS_FILE"):
    with open(os.environ["FAKE_CLAUDE_ARGS_FILE"], "a", encoding="utf-8") as f:
        f.write(json.dumps(sys.argv[1:]) + "\n")

mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "slow":
    time.sleep(30)
    sys.exit(0)
if mode == "fail":
    print("Not logged in. Please run /login", file=sys.stderr)
    sys.exit(2)

final = os.environ.get(
    "FAKE_CLAUDE_FINAL",
    "【做了什么】ran tests\n【结果/结论】all green\n【待你决策】无",
)
events = [
    {"type": "system", "subtype": "init", "session_id": "sess-123"},
    {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "name": "Bash", "input": {"command": "py -m unittest"}},
    ]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "content": "OK"}]}},
    {"type": "result", "subtype": "success", "is_error": False, "result": final, "session_id": "sess-123"},
]
for ev in events:
    sys.stdout.write(json.dumps(ev) + "\n")
    sys.stdout.flush()
