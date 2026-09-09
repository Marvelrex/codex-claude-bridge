"""Append-only JSONL notebook shared by Codex and Claude, plus a Markdown view."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

TRUNCATE_NOTE = "\n…(已截断，全文见 detail)"
_KEY_ORDER = ["seq", "ts", "from", "to", "kind", "mode", "body", "reply_to", "detail", "status"]


@dataclass
class Entry:
    seq: int
    ts: str
    from_: str
    to: str
    kind: str  # directive | report | note | system
    mode: Optional[str]  # analyze | execute | None
    body: str
    reply_to: Optional[int] = None
    detail: Optional[str] = None
    status: str = "open"  # open | done | error

    def to_json(self) -> str:
        d = asdict(self)
        d["from"] = d.pop("from_")
        return json.dumps({k: d[k] for k in _KEY_ORDER}, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "Entry":
        d = json.loads(line)
        d["from_"] = d.pop("from")
        return cls(**d)


def truncate_body(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + TRUNCATE_NOTE, True


def render_markdown(entries: list[Entry]) -> str:
    out = ["# Bridge Notebook", ""]
    for e in entries:
        mode = f" `{e.mode}`" if e.mode else ""
        reply = f" ↩ #{e.reply_to}" if e.reply_to is not None else ""
        out.append(f"## #{e.seq} {e.from_} → {e.to} · {e.kind}{mode}{reply} · {e.status}")
        out.append(f"*{e.ts}*")
        out.append("")
        out.append(e.body)
        out.append("")
        if e.detail:
            out.append(f"详情：[{e.detail}]({e.detail})")
            out.append("")
    return "\n".join(out)


class Notebook:
    def __init__(self, bridge_dir: Path):
        self.dir = Path(bridge_dir)
        self.path = self.dir / "notebook.jsonl"
        self.md_path = self.dir / "notebook.md"

    def read_all(self) -> list[Entry]:
        if not self.path.exists():
            return []
        entries: list[Entry] = []
        for line in self.path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(Entry.from_json(line))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue  # tolerate a partially written line
        return entries

    def next_seq(self) -> int:
        entries = self.read_all()
        return (entries[-1].seq + 1) if entries else 1

    def append(self, from_: str, to: str, kind: str, body: str, mode: Optional[str] = None,
               reply_to: Optional[int] = None, detail: Optional[str] = None,
               status: str = "open") -> Entry:
        e = Entry(self.next_seq(), datetime.now().isoformat(timespec="seconds"),
                  from_, to, kind, mode, body, reply_to, detail, status)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(e.to_json() + "\n")
            f.flush()
        self.render()
        return e

    def since(self, seq: int) -> list[Entry]:
        return [e for e in self.read_all() if e.seq > seq]

    def find_reply(self, seq: int) -> Optional[Entry]:
        for e in self.read_all():
            if e.reply_to == seq and e.kind in ("report", "system"):
                return e
        return None

    def mtime(self) -> float:
        return self.path.stat().st_mtime if self.path.exists() else 0.0

    def render(self) -> None:
        self.md_path.write_text(render_markdown(self.read_all()), "utf-8")
