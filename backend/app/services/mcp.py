"""Project-local MCP configuration and safe stdio tool discovery.

The configuration shape intentionally follows the common OpenCode/MCP model:
project-local JSON declares named local or remote servers. Discovery is explicit
and only starts local commands when the user requests it; configuration loading
never executes commands.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app.db.session import SessionLocal
from app.models.project import Project
from app.services.code_service import subprocess_env

_MAX_CONFIG_BYTES = 256_000
_MAX_RESPONSE_BYTES = 2_000_000
_CONFIG_PATHS = (".sdlc/mcp.json", ".opencode/mcp.json", "mcp.json")


def _project_root(project_id: int) -> Path:
    with SessionLocal() as db:
        project = db.get(Project, project_id)
    if project is None or not project.folder:
        raise ValueError("项目工作区不存在")
    return Path(project.folder).resolve()


def _load_config(root: Path) -> dict[str, Any]:
    for relative in _CONFIG_PATHS:
        path = root / relative
        if not path.is_file() or path.stat().st_size > _MAX_CONFIG_BYTES:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("mcp"), dict):
            payload = payload["mcp"]
        return payload if isinstance(payload, dict) else {}
    return {}


def _server_summary(name: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"name": name, "type": "invalid", "enabled": False, "error": "配置必须是对象"}
    server_type = str(raw.get("type") or ("remote" if raw.get("url") else "local"))
    command = raw.get("command", [])
    if isinstance(command, str):
        command = [command]
    if not isinstance(command, list) or not all(isinstance(item, str) and item for item in command):
        command = []
    environment = raw.get("environment", raw.get("env", {}))
    if not isinstance(environment, dict):
        environment = {}
    return {
        "name": name,
        "type": server_type,
        "enabled": bool(raw.get("enabled", True)),
        "command": command,
        "url": str(raw["url"]) if raw.get("url") else None,
        "env_keys": sorted(str(key) for key in environment),
        "tools": [],
        "error": None,
    }


def list_mcp_servers(project_id: int) -> list[dict[str, Any]]:
    root = _project_root(project_id)
    config = _load_config(root)
    return [_server_summary(name, raw) for name, raw in config.items()]


def _read_jsonrpc(stdout) -> dict[str, Any]:
    # MCP stdio messages normally use Content-Length framing. Accept newline
    # JSON too, which is useful for lightweight local development servers.
    first = stdout.readline()
    if not first:
        raise RuntimeError("MCP server 未返回响应")
    if first.startswith("Content-Length:"):
        length = int(first.split(":", 1)[1].strip())
        while True:
            line = stdout.readline()
            if line in ("\n", "\r\n", ""):
                break
        body = stdout.read(length)
        if len(body) != length:
            raise RuntimeError("MCP 响应不完整")
        return json.loads(body)
    return json.loads(first)


def discover_mcp_tools(project_id: int, name: str) -> dict[str, Any]:
    root = _project_root(project_id)
    config = _load_config(root)
    raw = config.get(name)
    summary = _server_summary(name, raw)
    if raw is None:
        raise FileNotFoundError(name)
    if not summary["enabled"]:
        summary["error"] = "MCP Server 已禁用"
        return summary
    if summary["type"] != "local":
        summary["error"] = "当前版本仅支持本地 stdio MCP 工具发现"
        return summary
    command = summary["command"]
    if not command:
        summary["error"] = "local MCP Server 缺少 command"
        return summary
    env = subprocess_env(project_id)
    configured_env = raw.get("environment", raw.get("env", {})) if isinstance(raw, dict) else {}
    if isinstance(configured_env, dict):
        for key, value in configured_env.items():
            if isinstance(key, str) and isinstance(value, str):
                env[key] = value
    try:
        process = subprocess.Popen(
            command,
            cwd=str(root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
            shell=False,
        )
        initialize = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "sdlc-agent", "version": "0.1"},
            },
        }
        assert process.stdin is not None
        process.stdin.write(json.dumps(initialize) + "\n")
        process.stdin.flush()
        response = _read_jsonrpc(process.stdout)
        if "error" in response:
            raise RuntimeError(str(response["error"]))
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) + "\n")
        process.stdin.flush()
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n")
        process.stdin.flush()
        tools_response = _read_jsonrpc(process.stdout)
        if "error" in tools_response:
            raise RuntimeError(str(tools_response["error"]))
        tools = tools_response.get("result", {}).get("tools", [])
        summary["tools"] = tools if isinstance(tools, list) else []
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        summary["error"] = str(exc)[:1000]
    finally:
        if 'process' in locals():
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
    return summary
