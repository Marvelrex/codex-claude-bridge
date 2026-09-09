"""Bridge configuration: defaults plus optional per-project overrides."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS: dict = {
    "max_body_chars": 600,
    "claude_timeout_sec": 1200,
    "poll_interval_sec": 1.0,
    "heartbeat_stale_sec": 30,
    "claude_bin": "claude",
    "analyze_args": ["--permission-mode", "plan"],
    "execute_args": ["--permission-mode", "acceptEdits", "--allowedTools", "Edit,Write,Bash"],
    "claude_model": None,
}


def load_config(bridge_dir: Path) -> dict:
    """Return DEFAULTS merged with <bridge_dir>/config.json if it exists."""
    cfg = dict(DEFAULTS)
    p = Path(bridge_dir) / "config.json"
    if p.exists():
        cfg.update(json.loads(p.read_text("utf-8")))
    return cfg


def write_default_config(bridge_dir: Path) -> Path:
    """Write DEFAULTS to config.json unless it already exists. Returns the path."""
    p = Path(bridge_dir) / "config.json"
    if not p.exists():
        p.write_text(json.dumps(DEFAULTS, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return p
