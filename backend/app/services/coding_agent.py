import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.models.llm_provider import LLMProvider
from app.services.code_service import (
    code_root,
    edit_code_file,
    list_code_files,
    project_python,
    read_code_file,
    run_tests,
    run_verify,
    write_code_file,
)
from app.services.llm_service import build_openai_client

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出当前代码目录中的文件。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取代码目录中的文件内容。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入或覆盖代码目录中的文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "在代码文件中替换一段文本。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "在代码目录中运行命令，仅允许 python、pytest、pip。",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "运行 pytest 测试并返回结果。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


@dataclass
class CodingResult:
    ok: bool
    verify: object
    tests: object
    turn_count: int


def _execute_command(project_id: int, command: str, timeout: int = 15) -> dict:
    tokens = command.strip().split()
    if not tokens:
        return {"ok": False, "stdout": "", "stderr": "空命令"}
    python = project_python(project_id)
    if tokens[0] in ("python", "python3"):
        cmd = [str(python), *tokens[1:]]
    elif tokens[0] == "pytest":
        cmd = [str(python), "-m", "pytest", *tokens[1:]]
    elif tokens[0] == "pip":
        cmd = [str(python), "-m", "pip", *tokens[1:]]
    else:
        return {"ok": False, "stdout": "", "stderr": "只允许 python、pytest、pip 命令"}
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(code_root(project_id)),
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:2000],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "stdout": (exc.stdout or "")[:2000],
            "stderr": (exc.stderr or "")[:2000],
            "timed_out": True,
        }


def execute_tool(project_id: int, name: str, args: dict) -> dict:
    try:
        if name == "list_files":
            tree = list_code_files(project_id)
            return {"ok": True, "files": [item.path for item in tree.files]}
        if name == "read_file":
            return {"ok": True, "content": read_code_file(project_id, args["path"])[:4000]}
        if name == "write_file":
            path = write_code_file(project_id, args["path"], args["content"])
            return {"ok": True, "path": path}
        if name == "edit_file":
            path = edit_code_file(
                project_id,
                args["path"],
                args["old_string"],
                args["new_string"],
            )
            return {"ok": True, "path": path}
        if name == "run_command":
            return _execute_command(project_id, args["command"])
        if name == "run_tests":
            result = run_tests(project_id)
            return {"ok": result.ok, "phase": result.phase, "output": result.output[:2000]}
        return {"ok": False, "error": f"未知工具: {name}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:2000]}


def _tests_passed(test_result) -> bool:
    if test_result is None:
        return False
    return test_result.ok or test_result.phase == "missing"


def run_coding_harness(
    project_id: int,
    provider: LLMProvider,
    project_name: str,
    project_description: str,
    previous_artifacts: str,
    max_turns: int = 8,
) -> CodingResult:
    client = build_openai_client(provider)
    system = (
        "你是一个编码 Agent，负责在给定工作区中创建可运行的 Python FastAPI 项目。"
        "你必须通过工具完成文件读写和验证，禁止输出 Markdown 代码围栏，"
        "禁止使用 passlib，requirements.txt 不写版本号。"
        "工作步骤建议：写文件，然后运行验证，最后运行测试。"
    )
    user = (
        f"项目名称：{project_name}\n"
        f"项目描述：{project_description}\n\n"
        f"前置文档：\n{previous_artifacts or '（无）'}\n\n"
        "请利用工具生成完整可运行的 FastAPI 项目，必须包含 requirements.txt、app/main.py、"
        "app/models.py、README.md、tests/test_app.py。"
        "完成后运行验证与测试，直到通过。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    verify = None
    tests = None

    for turn in range(max_turns):
        response = client.chat.completions.create(
            model=provider.default_model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=4000,
        )
        message = response.choices[0].message
        if message.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                        for tool_call in message.tool_calls
                    ],
                }
            )
            for tool_call in message.tool_calls:
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = execute_tool(project_id, tool_call.function.name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            verify = run_verify(project_id)
            tests = run_tests(project_id)
            if verify.ok and _tests_passed(tests):
                return CodingResult(ok=True, verify=verify, tests=tests, turn_count=turn + 1)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"[验证反馈]\n运行：{verify.output[:1200]}\n"
                        f"测试：{tests.output[:1200]}\n请继续修复并重新验证。"
                    ),
                }
            )
        else:
            if message.content:
                messages.append({"role": "assistant", "content": message.content})
            verify = run_verify(project_id)
            tests = run_tests(project_id)
            if verify.ok and _tests_passed(tests):
                return CodingResult(ok=True, verify=verify, tests=tests, turn_count=turn + 1)
            if turn < max_turns - 1:
                messages.append(
                    {
                        "role": "user",
                        "content": "验证仍未通过，请继续使用工具修复。",
                    }
                )

    return CodingResult(ok=False, verify=verify, tests=tests, turn_count=max_turns)
