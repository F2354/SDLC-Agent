import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.db.init_db import init_db
from app.services.event_bus import set_event_loop

logger = logging.getLogger("uvicorn.error")

# 前端构建产物目录（由 scripts/build.ps1 从 frontend/dist 拷贝而来）。
# 存在时后端直接托管前端，实现单端口运行，便于打包成桌面应用。
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception:
        logger.exception("数据库初始化失败，请检查 DATABASE_URL 与文件权限")
        raise
    # 注册事件循环，供线程池中的阶段运行发布 SSE 事件。
    set_event_loop(asyncio.get_running_loop())
    try:
        yield
    finally:
        set_event_loop(None)
        # 优雅关闭：等待阶段运行线程池中的任务结束。
        from app.services.stage_service import shutdown_stage_executor

        shutdown_stage_executor()


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root():
    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return {"message": "SDLC Agent API", "docs": "/docs"}


# 托管前端构建产物（存在时）。SPA 路由（如 /projects/1）刷新时回退到 index.html。
if STATIC_DIR.is_dir():
    _assets_dir = STATIC_DIR / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    _static_root = STATIC_DIR.resolve()

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        if full_path:
            candidate = (STATIC_DIR / full_path).resolve()
            # 防目录穿越：只允许返回静态目录内的真实文件。
            if candidate.is_file() and _static_root in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
