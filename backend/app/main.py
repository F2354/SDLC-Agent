import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.db.init_db import init_db

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception:
        logger.exception("数据库初始化失败，请检查 DATABASE_URL 与文件权限")
        raise
    try:
        yield
    finally:
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
    return {"message": "SDLC Agent API", "docs": "/docs"}
