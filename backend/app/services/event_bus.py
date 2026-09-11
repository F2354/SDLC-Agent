"""进程内 SSE 事件总线。

阶段运行在线程池中执行，而 SSE 订阅在事件循环中等待；
因此发布事件时必须通过事件循环的线程安全入口投递，
否则跨线程直接操作 asyncio.Queue 会出现数据竞争。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from typing import Any

logger = logging.getLogger("uvicorn.error")

# project_id -> 订阅者队列集合
_subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)
_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """应用启动时注册事件循环，关闭时置空。"""
    global _loop
    _loop = loop


def current_event_loop() -> asyncio.AbstractEventLoop | None:
    return _loop


def subscribe(project_id: int) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    with _lock:
        _subscribers[project_id].add(queue)
    return queue


def unsubscribe(project_id: int, queue: asyncio.Queue) -> None:
    with _lock:
        subscribers = _subscribers.get(project_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            _subscribers.pop(project_id, None)


def subscriber_count(project_id: int) -> int:
    with _lock:
        return len(_subscribers.get(project_id, ()))


def _dispatch(project_id: int, payload: dict[str, Any]) -> None:
    with _lock:
        queues = list(_subscribers.get(project_id, ()))
    for queue in queues:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            # 订阅端消费过慢：丢弃最旧事件，保证新事件仍能送达。
            try:
                queue.get_nowait()
                queue.put_nowait(payload)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass


def publish(project_id: int, event_type: str, data: dict[str, Any] | None = None) -> None:
    """从任意线程发布事件；无订阅者或事件循环已关闭时静默忽略。"""
    loop = _loop
    if loop is None or loop.is_closed():
        return
    payload = {"event": event_type, "data": data or {}}
    try:
        loop.call_soon_threadsafe(_dispatch, project_id, payload)
    except RuntimeError:
        logger.debug("事件循环已关闭，忽略事件 %s", event_type)
