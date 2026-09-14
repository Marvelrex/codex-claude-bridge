#!/usr/bin/env sh
# Git Bash / POSIX shim for zh2en. Usage: alias zh2en='/e/codex-claude-bridge/zh2en.sh'
DIR="$(cd "$(dirname "$0")" && pwd -W 2>/dev/null || pwd)"
if [ -n "$PYTHONPATH" ]; then
  PYTHONPATH="$DIR;$PYTHONPATH"
else
  PYTHONPATH="$DIR"
fi
export PYTHONPATH
if command -v py >/dev/null 2>&1; then
  exec py -3 -m bridge.translate "$@"
fi
exec python3 -m bridge.translate "$@"
