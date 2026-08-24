"""P3 业务运行记录。

LangGraph checkpointer 保存图状态；RunStore 保存业务任务状态和可查询事件，二者不混用。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


RunStatus = Literal["running", "completed", "failed", "cancelled", "waiting_for_input"]


@dataclass(slots=True)
class AgentRun:
    run_id: str
    session_id: str
    thread_id: str
    status: RunStatus = "running"
    prompt: str = ""
    steps: int = 0
    attempt: int = 1
    summary: str = ""
    error: str = ""
    pending_user_input: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RunStore:
    """基于 JSONL 事件的最小异步运行存储。"""

    def __init__(self, base_dir: str | Path = "data/runs") -> None:
        self.base_dir = Path(base_dir)
        self._lock = asyncio.Lock()

    def create_run_id(self) -> str:
        return uuid.uuid4().hex

    async def create(
        self,
        *,
        session_id: str,
        thread_id: str,
        prompt: str,
        run_id: str | None = None,
        attempt: int = 1,
    ) -> AgentRun:
        run = AgentRun(
            run_id=run_id or self.create_run_id(),
            session_id=session_id,
            thread_id=thread_id,
            prompt=prompt,
            attempt=max(int(attempt), 1),
        )
        await self.append_event(run.run_id, "run.created", asdict(run))
        return run

    async def append_event(
        self,
        run_id: str,
        event: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "event": event,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "data": data or {},
        }
        async with self._lock:
            await asyncio.to_thread(self._append_sync, run_id, record)

    async def get(self, run_id: str) -> AgentRun | None:
        async with self._lock:
            records = await asyncio.to_thread(self._read_sync, run_id)
        return self._rebuild(records)

    async def list_runs(
        self,
        *,
        session_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        async with self._lock:
            runs = await asyncio.to_thread(self._list_sync)
        filtered = [
            run for run in runs
            if (session_id is None or run.session_id == session_id)
            and (status is None or run.status == status)
        ]
        filtered.sort(key=lambda item: item.updated_at, reverse=True)
        return filtered[:max(int(limit), 1)]

    async def read_events(self, run_id: str) -> list[dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(self._read_sync, run_id)

    async def set_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        steps: int | None = None,
        summary: str | None = None,
        error: str | None = None,
        pending_user_input: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        """追加状态事件并返回重建后的运行记录。"""

        current = await self.get(run_id)
        if current is None:
            return None
        if current.status in {"completed", "failed", "cancelled"} and status != current.status:
            return current
        data: dict[str, Any] = {"status": status}
        if steps is not None:
            data["steps"] = max(int(steps), 0)
        if summary is not None:
            data["summary"] = summary
        if error is not None:
            data["error"] = error
        if pending_user_input is not None:
            data["pending_user_input"] = pending_user_input
        await self.append_event(run_id, "run.status_changed", data)
        return await self.get(run_id)

    async def recover_interrupted(self) -> int:
        """服务启动时将遗留 running 任务标为失败。"""

        runs = await self.list_runs(status="running", limit=100000)
        for run in runs:
            await self.set_status(
                run.run_id,
                "failed",
                steps=run.steps,
                error="服务进程中断，任务未完成",
            )
        return len(runs)

    def _path(self, run_id: str) -> Path:
        return self.base_dir / f"{run_id}.jsonl"

    def _append_sync(self, run_id: str, record: dict[str, Any]) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        with self._path(run_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read_sync(self, run_id: str) -> list[dict[str, Any]]:
        path = self._path(run_id)
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def _list_sync(self) -> list[AgentRun]:
        if not self.base_dir.exists():
            return []
        runs: list[AgentRun] = []
        for path in self.base_dir.glob("*.jsonl"):
            run = self._rebuild(self._read_sync(path.stem))
            if run is not None:
                runs.append(run)
        return runs

    @staticmethod
    def _rebuild(records: list[dict[str, Any]]) -> AgentRun | None:
        if not records:
            return None
        first = records[0].get("data", {})
        if not isinstance(first, dict) or not first.get("run_id"):
            return None
        fields = {
            key: first[key]
            for key in AgentRun.__dataclass_fields__
            if key in first
        }
        run = AgentRun(**fields)
        for record in records[1:]:
            data = record.get("data", {})
            if not isinstance(data, dict):
                data = {}
            run.updated_at = record.get("created_at", run.updated_at)
            status = data.get("status")
            if status in {"running", "completed", "failed", "cancelled", "waiting_for_input"}:
                run.status = status
            for key in ("steps", "summary", "error", "pending_user_input"):
                if key in data:
                    setattr(run, key, data[key])
        return run
