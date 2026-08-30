"""FastAPI 应用入口。

同一个进程同时提供：
- REST / SSE 业务 API（``/api/*``）
- 前端静态资源（``apps/web/dist`` 的构建产物，同源零 CORS）
- （后续）WebSocket 语音通道

借鉴 EchoBot ``echobot/app/create_app.py`` 的「同进程出 API + 托管静态前端」
设计，一个 Uvicorn 端口搞定整站。
"""

from __future__ import annotations

from pathlib import Path
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import chat, persona, sessions, voice, web, runs
from memory.chat_db import chat_db

# 前端构建产物目录（cd apps/web && npm run build）
WEB_DIST = Path(__file__).resolve().parents[1] / "apps" / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(chat_db.init_db)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="MutiRoleAgent API",
        description="多角色 Agent 后端服务",
        lifespan=lifespan,
    )

    # ---- 前端托管（构建产物存在时才挂载） ----
    index_html = WEB_DIST / "index.html"
    if index_html.exists():
        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(index_html)

        assets_dir = WEB_DIST / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    else:
        @app.get("/", include_in_schema=False)
        async def index() -> dict[str, str]:
            return {
                "name": "MutiRoleAgent API",
                "docs": "/docs",
                "hint": "未找到前端构建产物，请先在 apps/web 执行 npm run build",
            }

    # ---- 业务路由 ----
    app.include_router(chat.router, prefix="/api")
    app.include_router(voice.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(persona.router, prefix="/api")
    app.include_router(web.router, prefix="/api")
    app.include_router(runs.router, prefix="/api/v1")

    return app


app = create_app()
