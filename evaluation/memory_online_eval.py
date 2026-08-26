"""通过真实 FastAPI SSE 接口验证 L2 Memory 的跨会话效果。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memory.l2_memory import l2_memory_store


async def _chat(client: httpx.AsyncClient, query: str, session_id: str, user_id: str) -> dict:
    chunks: list[str] = []
    events: list[str] = []
    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={
            "query": query,
            "session_id": session_id,
            "user_id": user_id,
            "persona": "Cyrene",
        },
    ) as response:
        current_event = "message"
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                current_event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].lstrip()
                events.append(current_event)
                if current_event == "chunk":
                    chunks.append(data)
    return {
        "status_code": response.status_code,
        "answer": "".join(chunks),
        "events": events,
    }


async def run(base_url: str, *, in_process: bool = False) -> dict:
    user_id = f"memory-online-{uuid.uuid4().hex[:8]}"
    first_session = f"{user_id}-write"
    second_session = f"{user_id}-read"
    timeout = httpx.Timeout(180, connect=20)
    transport = None
    if in_process:
        from api.main import create_app

        transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        transport=transport,
    ) as client:
        health = await client.get("/api/chat/health")
        if health.status_code != 200:
            raise RuntimeError(f"API unavailable: {health.status_code}")

        write = await _chat(
            client,
            "请记住：我喜欢太空科幻动漫，推荐时优先考虑这类作品。",
            first_session,
            user_id,
        )

        # L2 写入是后台任务，最多等待 10 秒，避免固定长等待。
        memory_count = 0
        for _ in range(10):
            memory_count = len(l2_memory_store.search(user_id, "太空科幻动漫", 4))
            if memory_count:
                break
            await asyncio.sleep(1)

        read = await _chat(
            client,
            "现在给我推荐一部动漫，并说明为什么适合我。",
            second_session,
            user_id,
        )

    answer = read["answer"]
    used_preference = any(word in answer for word in ("科幻", "太空", "宇宙"))
    return {
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "suite": "memory-online-v1",
        "endpoint": base_url,
        "user_id": user_id,
        "write_turn": write,
        "read_turn": read,
        "metrics": {
            "write_http_ok": write["status_code"] == 200,
            "memory_persisted": memory_count > 0,
            "read_http_ok": read["status_code"] == 200,
            "answer_used_preference": used_preference,
        },
        "passed": (
            write["status_code"] == 200
            and memory_count > 0
            and read["status_code"] == 200
            and used_preference
        ),
    }


def save_report(report: dict) -> Path:
    target_dir = PROJECT_ROOT / "evaluation" / "reports"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"memory_online_{datetime.now():%Y%m%d_%H%M%S}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行 L2 Memory FastAPI 在线评测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="不经 TCP 端口，直接通过 FastAPI ASGI 路由执行真实业务链路",
    )
    args = parser.parse_args()
    report = asyncio.run(run(args.base_url, in_process=args.in_process))
    path = save_report(report)
    print(json.dumps({"passed": report["passed"], "report": str(path)}, ensure_ascii=False))
