"""SSE 事件流：把阶段运行过程中的状态变化实时推送给前端。"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.services.event_bus import subscribe, unsubscribe

router = APIRouter(prefix="/projects", tags=["events"])

# 心跳间隔：定期发送注释行，避免代理/浏览器因空闲断开连接。
_HEARTBEAT_SECONDS = 15


@router.get("/{project_id}/events")
async def project_events(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    queue = subscribe(project_id)

    async def event_stream():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(
                        queue.get(), timeout=_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                data = json.dumps(payload["data"], ensure_ascii=False)
                yield f"event: {payload['event']}\ndata: {data}\n\n"
        finally:
            unsubscribe(project_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
