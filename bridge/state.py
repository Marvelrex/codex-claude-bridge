"""Watcher-side persistent state (state.json)."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class State:
    session_id: Optional[str] = None  # Claude session to --resume
    last_processed: int = 0  # seq of last directive handled
    running_seq: Optional[int] = None  # directive currently being processed
    heartbeat: float = 0.0  # epoch seconds of last watcher tick

    @classmethod
    def load(cls, bridge_dir: Path) -> "State":
        p = Path(bridge_dir) / "state.json"
        if not p.exists():
            return cls()
        try:
            d = json.loads(p.read_text("utf-8"))
            defaults = asdict(cls())
            return cls(**{k: d.get(k, v) for k, v in defaults.items()})
        except (json.JSONDecodeError, TypeError, AttributeError):
            return cls()

    def save(self, bridge_dir: Path) -> None:
        p = Path(bridge_dir) / "state.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), "utf-8")
        tmp.replace(p)

    def touch(self) -> None:
        self.heartbeat = time.time()

    def heartbeat_age(self) -> float:
        return time.time() - self.heartbeat
