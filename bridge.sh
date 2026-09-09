#!/usr/bin/env sh
# Git Bash / POSIX shim for the bridge CLI. Usage: alias bridge='/e/AgentsCrossPlatformFramework/bridge.sh'
DIR="$(cd "$(dirname "$0")" && pwd -W 2>/dev/null || pwd)"
if [ -n "$PYTHONPATH" ]; then
  PYTHONPATH="$DIR;$PYTHONPATH"
else
  PYTHONPATH="$DIR"
fi
export PYTHONPATH
if command -v py >/dev/null 2>&1; then
  exec py -3 -m bridge "$@"
fi
exec python3 -m bridge "$@"
