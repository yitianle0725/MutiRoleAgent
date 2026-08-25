"""Send the 100-case ACGN dataset through the real FastAPI SSE endpoint.

Start the backend first, for example:
``D:/develop/Anaconda/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000``
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATASET = PROJECT_ROOT / "evaluation" / "datasets" / "acgn_retrieval_100.json"
REPORTS = PROJECT_ROOT / "evaluation" / "reports"


def _parse_sse_block(block: str) -> tuple[str, str]:
    event = "message"
    data_lines: list[str] = []
    for line in block.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    return event, "\n".join(data_lines)


async def _send_case(client: httpx.AsyncClient, case: dict, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        started = time.perf_counter()
        session_id = f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"
        result = {
            "id": case["id"],
            "domain": case.get("domain", "unknown"),
            "category": case.get("category", "unknown"),
            "query": case["query"],
            "status_code": None,
            "answer": "",
            "tool_calls": [],
            "events": Counter(),
            "error": None,
        }
        try:
            async with client.stream(
                "POST",
                "/api/chat/stream",
                json={"query": case["query"], "session_id": session_id, "persona": "Cyrene"},
            ) as response:
                result["status_code"] = response.status_code
                chunks: list[str] = []
                buffer = ""
                async for raw_line in response.aiter_lines():
                    if raw_line == "":
                        if buffer.strip():
                            event, data = _parse_sse_block(buffer)
                            result["events"][event] += 1
                            if event == "chunk":
                                chunks.append(data)
                            elif event == "tool":
                                try:
                                    result["tool_calls"].append(json.loads(data))
                                except json.JSONDecodeError:
                                    result["tool_calls"].append({"raw": data})
                            elif event == "error":
                                result["error"] = data
                            buffer = ""
                    else:
                        buffer += raw_line + "\n"
                if buffer.strip():
                    event, data = _parse_sse_block(buffer)
                    result["events"][event] += 1
                    if event == "chunk":
                        chunks.append(data)
                result["answer"] = "".join(chunks)
                if response.status_code >= 400:
                    result["error"] = result["error"] or f"HTTP {response.status_code}"
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        result["events"] = dict(result["events"])
        result["tool_names"] = [item.get("tool_name", "") for item in result["tool_calls"]]
        return result


async def run(base_url: str, concurrency: int, timeout: float) -> Path:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    request_timeout = httpx.Timeout(timeout, connect=20.0)
    semaphore = asyncio.Semaphore(concurrency)
    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=base_url, timeout=request_timeout, limits=limits) as client:
        response = await client.get("/api/chat/health")
        if response.status_code != 200:
            raise RuntimeError(f"FastAPI health check failed: {response.status_code} {response.text}")
        results = await asyncio.gather(*(_send_case(client, case, semaphore) for case in cases))

    latencies = [item["latency_ms"] for item in results]
    successful = [item for item in results if item["status_code"] == 200 and not item["error"]]
    category_report: dict[str, dict[str, float | int]] = {}
    for category in sorted({item["category"] for item in results}):
        group = [item for item in results if item["category"] == category]
        category_report[category] = {
            "total": len(group),
            "completed": sum(1 for item in group if item["status_code"] == 200),
            "error_rate": round(sum(1 for item in group if item["error"]) / len(group), 4),
            "mean_latency_ms": round(statistics.mean(item["latency_ms"] for item in group), 2),
        }

    report = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "endpoint": f"{base_url}/api/chat/stream",
        "request_count": len(cases),
        "concurrency": concurrency,
        "wall_time_seconds": round(time.perf_counter() - started, 2),
        "summary": {
            "http_200": sum(1 for item in results if item["status_code"] == 200),
            "completed_without_error": len(successful),
            "error_count": sum(1 for item in results if item["error"]),
            "mean_latency_ms": round(statistics.mean(latencies), 2),
            "p95_latency_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2),
            "tool_call_rate": round(sum(1 for item in results if item["tool_names"]) / len(results), 4),
        },
        "categories": category_report,
        "results": results,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"fastapi_load_100_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"报告已保存: {path}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="通过 FastAPI SSE 并发执行 100 条 ACGN 请求")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    asyncio.run(run(args.base_url.rstrip("/"), args.concurrency, args.timeout))


if __name__ == "__main__":
    main()
