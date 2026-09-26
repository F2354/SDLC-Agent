import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.models.llm_provider import LLMProvider
from app.services.agents import get_agent_permissions
from app.services.code_service import (
    _PACKAGE_NAME_RE,
    code_root,
    commit_project_changes,
    edit_code_file,
    git_diff,
    git_log,
    git_status,
    list_code_files,
    project_python,
    read_code_file,
    run_stage_tests,
    run_verify,
    subprocess_env,
    write_code_file,
)
from app.services.llm_service import build_openai_client
from app.services.skills import skill_context

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
            "description": (
                "在代码目录中运行命令。仅允许 python <脚本>、pytest、"
                "pip install/uninstall/list/show；禁止 python -c 与自定义 pip 源。"
            ),
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
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "查看项目工作区的 Git 状态（分支、未提交的变更文件）。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "查看项目工作区未提交的代码差异。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "查看项目工作区的提交历史，用于了解此前各阶段的进展。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回的提交条数，默认 10，最大 50。",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": (
                "把当前工作区的改动提交为一个 Git 提交。"
                "仓库尚未初始化时会自动初始化。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "提交说明。"}
                },
                "required": ["message"],
            },
        },
    },
]

# Git 工具统一走 git 权限键，与 read / edit / bash 区分。
_GIT_TOOLS = frozenset({"git_status", "git_diff", "git_log", "git_commit"})

_READ_TOOLS = frozenset({"list_files", "read_file"})
_EDIT_TOOLS = frozenset({"write_file", "edit_file"})


@dataclass
class CodingResult:
    ok: bool
    verify: object
    tests: object
    turn_count: int


# 允许通过 `python -m` 执行的模块白名单。
_ALLOWED_MODULES = {"pytest", "pip", "py_compile", "compileall"}

# 允许传给 `python <script>` 的开关；其余一律拒绝（尤其是 -c/-m/-- 等可执行入口）。
_ALLOWED_PYTHON_FLAGS = {"-B", "-O", "-OO", "-u", "-W", "-X"}


def _reject(reason: str) -> dict:
    return {"ok": False, "stdout": "", "stderr": reason}


def _validate_pip_args(args: list[str]) -> str | None:
    """校验 pip 参数：只允许安装/卸载白名单内的包名。"""
    if not args:
        return "pip 命令缺少参数"
    if args[0] not in ("install", "uninstall", "list", "show"):
        return "pip 只允许 install、uninstall、list、show 子命令"
    for token in args[1:]:
        if token.startswith("-"):
            # 只允许少量安全开关，阻断 --index-url 等可劫持依赖源的参数。
            if token not in ("--upgrade", "-U", "--quiet", "-q", "--no-input", "-y"):
                return f"pip 参数不被允许：{token}"
        elif not _PACKAGE_NAME_RE.match(token):
            return f"pip 包名不合法：{token}"
    if args[0] == "install" and not any(
        not token.startswith("-") for token in args[1:]
    ):
        return "pip install 至少需要一个包名"
    return None


def _build_command(project_id: int, tokens: list[str]) -> tuple[list[str] | None, str | None]:
    """把 Agent 给出的命令翻译成受控的 argv。返回 (命令, 错误信息)。"""
    python = str(project_python(project_id))
    program, args = tokens[0], tokens[1:]

    if program == "pytest":
        for token in args:
            if token.startswith("-c"):
                return None, "pytest 不允许通过 -c 加载外部配置"
        return [python, "-m", "pytest", *args], None

    if program == "pip" or (program == "python" and args and args[0] == "-m" and len(args) > 1 and args[1] == "pip"):
        pip_args = args[2:] if program == "python" else args
        error = _validate_pip_args(pip_args)
        return (None, error) if error else ([python, "-m", "pip", *pip_args], None)

    if program in ("python", "python3"):
        # python -m <module>：模块必须在白名单内（或显式开启不安全模式）。
        if args and args[0] == "-m":
            module = args[1] if len(args) > 1 else ""
            if module not in _ALLOWED_MODULES:
                if not settings.allow_unsafe_commands:
                    return None, f"python -m 仅允许模块：{sorted(_ALLOWED_MODULES)}"
            return [python, "-m", module, *args[2:]], None

        # python -c "..."：等价于任意代码执行，默认禁止。
        if args and args[0] == "-c":
            if not settings.allow_unsafe_commands:
                return None, "python -c 已被禁用（等价于任意代码执行）"
            return [python, "-c", *args[1:]], None

        # python <script>：只允许运行工作区内的脚本文件，拒绝其它开关。
        script = next((token for token in args if not token.startswith("-")), None)
        if script is None:
            return None, "python 命令缺少脚本路径"
        for token in args:
            if token.startswith("-") and token not in _ALLOWED_PYTHON_FLAGS:
                return None, f"python 参数不被允许：{token}"
        try:
            target = (code_root(project_id) / script).resolve()
            target.relative_to(code_root(project_id).resolve())
        except (ValueError, OSError):
            return None, f"脚本必须在代码工作区内：{script}"
        if not target.is_file():
            return None, f"脚本不存在：{script}"
        return [python, *args], None

    return None, "只允许 python、pytest、pip 命令"


def _execute_command(project_id: int, command: str, timeout: int = 15) -> dict:
    tokens = command.strip().split()
    if not tokens:
        return _reject("空命令")
    cmd, error = _build_command(project_id, tokens)
    if error:
        return _reject(error)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(code_root(project_id)),
            env=subprocess_env(project_id),
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
    except (OSError, ValueError) as exc:
        return _reject(f"命令执行失败：{exc}")


def execute_tool(project_id: int, name: str, args: dict, agent_name: str = "developer") -> dict:
    try:
        if name in _READ_TOOLS:
            permission_key = "read"
        elif name in _EDIT_TOOLS:
            permission_key = "edit"
        elif name in _GIT_TOOLS:
            permission_key = "git"
        else:
            permission_key = "bash"
        permission = get_agent_permissions(project_id, agent_name).get(permission_key, "ask")
        if permission == "deny":
            return {"ok": False, "error": f"Agent {agent_name} 没有 {permission_key} 工具权限"}
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
            result = run_stage_tests(project_id)
            return {"ok": result.ok, "phase": result.phase, "output": result.output[:2000]}
        if name == "git_status":
            return {"ok": True, **git_status(project_id)}
        if name == "git_diff":
            return {"ok": True, "diff": git_diff(project_id)[:4000]}
        if name == "git_log":
            try:
                limit = int(args.get("limit") or 10)
            except (TypeError, ValueError):
                limit = 10
            return {"ok": True, "commits": git_log(project_id, limit)}
        if name == "git_commit":
            message = str(args.get("message") or "").strip()
            if not message:
                return {"ok": False, "error": "提交说明不能为空"}
            return {"ok": True, **commit_project_changes(project_id, message)}
        return {"ok": False, "error": f"未知工具: {name}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:2000]}


def _tests_passed(test_result) -> bool:
    if test_result is None:
        return False
    return test_result.ok


def run_coding_harness(
    project_id: int,
    provider: LLMProvider,
    project_name: str,
    project_description: str,
    previous_artifacts: str,
    max_turns: int = 8,
    model_name: str | None = None,
) -> CodingResult:
    client = build_openai_client(provider)
    resolved_model = model_name or provider.default_model
    system = (
        "你是一个编码 Agent，负责在给定工作区中创建可运行的 Python FastAPI 项目。"
        "你必须通过工具完成文件读写和验证，禁止输出 Markdown 代码围栏，"
        "禁止使用 passlib，requirements.txt 不写版本号。"
        "工作步骤建议：写文件，然后运行验证，最后运行测试。"
        "可用 git_status / git_diff / git_log 查看工作区现状与历史进展；"
        "阶段结束时系统会自动提交产物，无需手动调用 git_commit。"
    )
    skills = skill_context(project_id, "FastAPI Python coding testing Git", limit=4)
    user = (
        f"项目名称：{project_name}\n"
        f"项目描述：{project_description}\n\n"
        f"前置文档：\n{previous_artifacts or '（无）'}\n\n"
        f"项目 Skills（仅作为本项目规则参考）：\n{skills or '（无）'}\n\n"
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
            model=resolved_model,
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
                result = execute_tool(project_id, tool_call.function.name, args, agent_name="developer")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            verify = run_verify(project_id)
            tests = run_stage_tests(project_id)
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
            tests = run_stage_tests(project_id)
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
