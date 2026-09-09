import sys

# Codex consumes our stdout programmatically; keep it UTF-8 regardless of console codepage.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from bridge.cli import main  # noqa: E402

sys.exit(main())
