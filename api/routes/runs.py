"""后台 Agent run 查询、事件、取消和重试接口。"""

from fastapi import APIRouter, HTTPException

from channels.platforms.fastapi import conversation_coordinator

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = await conversation_coordinator.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run": run.__dict__ if hasattr(run, "__dict__") else {field: getattr(run, field) for field in run.__dataclass_fields__}}


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str):
    run = await conversation_coordinator.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run_id, "events": await conversation_coordinator.get_run_events(run_id)}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    run = await conversation_coordinator.cancel_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run": {field: getattr(run, field) for field in run.__dataclass_fields__}}


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str):
    try:
        result = await conversation_coordinator.retry_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"result": result.__dict__ if hasattr(result, "__dict__") else {field: getattr(result, field) for field in result.__dataclass_fields__}}
