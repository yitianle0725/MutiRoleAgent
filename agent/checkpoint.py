"""项目层的轻量 checkpoint 元数据存储。

完整图状态由 LangGraph checkpointer 保存；这里仅记录业务运行需要的索引和摘要，
用于在没有直接查询 saver 的部署中恢复 RunStore 状态。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AgentCheckpoint:
    run_id: str
    session_id: str
    thread_id: str
    step: int = 0
    summary: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CheckpointStore:
    """按 run 保存轻量 checkpoint 索引，不复制 LangGraph messages。"""

    def __init__(self, base_dir: str | Path = "data/checkpoints") -> None:
        self.base_dir = Path(base_dir)
        self._lock = asyncio.Lock()

    async def save(self, checkpoint: AgentCheckpoint) -> None:
        async with self._lock:
            await asyncio.to_thread(self._save_sync, checkpoint)

    async def latest(self, run_id: str) -> AgentCheckpoint | None:
        async with self._lock:
            return await asyncio.to_thread(self._latest_sync, run_id)

    def _path(self, run_id: str) -> Path:
        return self.base_dir / f"{run_id}.json"

    def _save_sync(self, checkpoint: AgentCheckpoint) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._path(checkpoint.run_id).write_text(
            json.dumps(asdict(checkpoint), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _latest_sync(self, run_id: str) -> AgentCheckpoint | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return AgentCheckpoint(**data)
        except (OSError, json.JSONDecodeError, TypeError):
            return None


checkpoint_store = CheckpointStore()
