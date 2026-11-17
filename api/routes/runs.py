"""后台 Agent run 查询、事件、取消和重试接口。"""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request

router = APIRouter(tags=["runs"])
RunId = Annotated[str, Path(pattern=r"^[a-zA-Z0-9_-]{1,128}$")]


@router.get("/runs/{run_id}")
async def get_run(run_id: RunId, request: Request):
    run = await request.app.state.conversation_coordinator.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run": asdict(run)}


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: RunId, request: Request):
    coordinator = request.app.state.conversation_coordinator
    run = await coordinator.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run_id, "events": await coordinator.get_run_events(run_id)}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: RunId, request: Request):
    run = await request.app.state.conversation_coordinator.cancel_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run": asdict(run)}


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: RunId, request: Request):
    try:
        result = await request.app.state.conversation_coordinator.retry_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"result": asdict(result)}
