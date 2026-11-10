"""极简长期记忆：全量写入用户消息，JSON 持久化。

当前版本刻意不做写入门控、不做来源标识——这是后续实验的基线。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

DATA_DIR = Path(__file__).resolve().parent / "data"


def _path(character: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in character if ch.isalnum() or ch in "_-") or "character"
    return DATA_DIR / f"memory_{safe}.json"


def load_memories(character: str) -> list[dict]:
    path = _path(character)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save_memories(character: str, memories: list[dict]) -> None:
    _path(character).write_text(
        json.dumps(memories[-200:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_memory(character: str, text: str, turn: int) -> dict:
    memories = load_memories(character)
    memory = {
        "id": f"m_{uuid4().hex[:8]}",
        "text": text.strip(),
        "turn": turn,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    memories.append(memory)
    save_memories(character, memories)
    return memory


def clear_memories(character: str) -> None:
    path = _path(character)
    if path.exists():
        path.unlink()
