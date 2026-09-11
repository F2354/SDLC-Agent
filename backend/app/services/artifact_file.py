"""将阶段文档产物同步写入项目 folder 下的 docs/ 目录。

代码与测试已落在用户指定的 folder（见 code_service._project_root）；
本模块补齐文档产物：每生成/更新一个阶段文档，就把 Markdown 写入 ``{folder}/docs/``，
使最终成品成为自包含的项目文件夹（类似 codex 的工作区）。

平台级 SQLite 仍保留文档内容与版本、状态，供前端展示与追溯。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.models.stage_run import Artifact

logger = logging.getLogger("uvicorn.error")

# 文件名非法字符（Windows / Unix 通用）。
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _sanitize(name: str) -> str:
    cleaned = _INVALID_CHARS.sub("-", (name or "").strip())
    cleaned = cleaned.strip(". ")
    return cleaned or "untitled"


def artifact_doc_path(project_id: int, artifact: Artifact) -> Path | None:
    """计算文档产物应写入的文件路径（不实际写入）。无法定位 folder 时返回 None。"""
    from app.services.code_service import _project_root

    try:
        root = _project_root(project_id)
    except Exception:  # noqa: BLE001
        return None
    docs_dir = root / "docs"
    stage_label = _sanitize(artifact.type or "doc")
    title_label = _sanitize(artifact.title)
    return docs_dir / f"{stage_label} - {title_label}.md"


def write_artifact_file(project_id: int, artifact: Artifact) -> Path | None:
    """把文档产物写入项目 folder/docs/ 下的 Markdown 文件，返回写入路径；失败返回 None。"""
    path = artifact_doc_path(project_id, artifact)
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.content_md or "", encoding="utf-8")
    except OSError:  # noqa: BLE001
        logger.warning("文档产物写文件失败: %s", path)
        return None
    return path
