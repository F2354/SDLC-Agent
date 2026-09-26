"""内置 Agent 角色注册表。

在此之前，7 个 agent 角色只是 seed 表里的三行文字（编码 / 名称 / 描述），
提示词还是按「阶段」组织的 —— 也就是说角色是名义上的，Agent 行为不随角色变化。

本模块把角色变成一等公民：每个角色 = 职责 + **工具子集** + **输出契约**。
过程模型通过 ``stage_service.STAGE_AGENT_CODE`` 把阶段绑定到角色，
角色再决定这一阶段能用什么工具、产出什么、能不能改产物。

设计要点（也是「子 Agent 分工」的实质）：

- **评审角色只读**。reviewer 没有 write_file / edit_file，
  从机制上保证「评审不修改被评审的产物」，而不是靠提示词自觉。
- **需求/架构/设计角色不能执行命令**。没有 run_command / run_tests，
  避免文档类角色误触代码运行。
- **只有开发与测试角色能跑测试**，且写入目标不同（code/ 与 tests/）。
- **统筹角色只读**，职责是汇总与调度，不直接产出实体。

依赖方向：本模块不导入任何 app.services 下的其它模块，
由 coding_agent 单向依赖它，避免循环导入。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 工具按能力分组，角色用「并集」表达自己的子集。
READ_TOOLS = frozenset({"list_files", "read_file"})
WRITE_TOOLS = frozenset({"write_file", "edit_file"})
SHELL_TOOLS = frozenset({"run_command", "run_tests"})
GIT_TOOLS = frozenset({"git_status", "git_diff", "git_log", "git_commit"})

ALL_TOOLS = READ_TOOLS | WRITE_TOOLS | SHELL_TOOLS | GIT_TOOLS


@dataclass(frozen=True)
class AgentRoleSpec:
    """一个 agent 角色的完整定义。"""

    code: str
    name: str
    duty: str
    toolset: frozenset[str]
    output_contract: str
    # 产物写入目标：仅对拥有写权限的角色有意义。
    write_target: str = ""
    extra_rules: tuple[str, ...] = field(default_factory=tuple)

    @property
    def can_write(self) -> bool:
        return bool(self.toolset & WRITE_TOOLS)

    @property
    def can_run_shell(self) -> bool:
        return bool(self.toolset & SHELL_TOOLS)


_REQUIREMENTS_ANALYST = AgentRoleSpec(
    code="requirements_analyst",
    name="需求分析师",
    duty="访谈用户、整理功能与非功能需求，编写需求规格说明书。",
    toolset=READ_TOOLS | WRITE_TOOLS | GIT_TOOLS,
    output_contract=(
        "需求条目使用 RQ-001 连续编号；用例使用 UC-001 编号，"
        "并逐条标注其来源需求（如「来源：RQ-001」）。"
    ),
    write_target="docs",
    extra_rules=("不执行任何命令，只做需求整理与文档编写。",),
)

_ARCHITECT = AgentRoleSpec(
    code="architect",
    name="架构师",
    duty="负责系统总体架构、模块划分、技术选型与部署设计。",
    toolset=READ_TOOLS | WRITE_TOOLS | GIT_TOOLS,
    output_contract=(
        "模块使用 MOD-001 编号，并标注其实现的需求 RQ-xxx 或用例 UC-xxx；"
        "技术选型需给出理由。"
    ),
    write_target="docs",
    extra_rules=("不执行任何命令，只做架构设计。",),
)

_DESIGNER = AgentRoleSpec(
    code="designer",
    name="设计工程师",
    duty="负责类设计、数据库设计、接口定义与关键流程设计。",
    toolset=READ_TOOLS | WRITE_TOOLS | GIT_TOOLS,
    output_contract=(
        "接口必须关联到具体模块 MOD-xxx；数据库设计需给出表结构与字段类型。"
    ),
    write_target="docs",
    extra_rules=("不执行任何命令，只做详细设计。",),
)

_DEVELOPER = AgentRoleSpec(
    code="developer",
    name="开发工程师",
    duty="负责代码实现、依赖声明与运行验证，产出可运行的项目代码。",
    toolset=ALL_TOOLS,
    output_contract=(
        "必须通过工具真实写盘，禁止输出 Markdown 代码围栏；"
        "必须包含 requirements.txt 与可运行入口，并保证验证与测试通过。"
    ),
    write_target="code",
    extra_rules=(
        "requirements.txt 只写包名，不写版本号。",
        "禁止使用 passlib。",
    ),
)

_TESTER = AgentRoleSpec(
    code="tester",
    name="测试工程师",
    duty="制定测试策略、编写并执行测试用例，输出测试结果。",
    toolset=READ_TOOLS | WRITE_TOOLS | SHELL_TOOLS | GIT_TOOLS,
    output_contract=(
        "测试用例使用 TC-001 连续编号，并标注其验证的需求 RQ-xxx 或模块 MOD-xxx；"
        "必须真实运行测试并给出通过情况。"
    ),
    write_target="tests",
    extra_rules=("测试文件写入 tests/ 目录，不得修改被测代码。",),
)

_REVIEWER = AgentRoleSpec(
    code="reviewer",
    name="评审",
    duty="对阶段产物做完整性与一致性审查，给出通过或修改建议。",
    toolset=READ_TOOLS | GIT_TOOLS,
    output_contract=(
        "输出检查清单逐项结论与一致性问题；引用制品中的实体编号作为证据。"
    ),
    write_target="",
    extra_rules=("你没有写权限：评审结论只能作为意见输出，不得修改任何产物。",),
)

_COORDINATOR = AgentRoleSpec(
    code="coordinator",
    name="统筹协调",
    duty="调度阶段 agent、汇总各阶段上下文，向用户汇报进展与下一步建议。",
    toolset=READ_TOOLS | GIT_TOOLS,
    output_contract="汇总说明与下一步建议；不产出实体编号，不直接修改产物。",
    write_target="",
    extra_rules=("你没有写权限，职责是统筹与汇总。",),
)


_ROLE_LIST: tuple[AgentRoleSpec, ...] = (
    _COORDINATOR,
    _REQUIREMENTS_ANALYST,
    _ARCHITECT,
    _DESIGNER,
    _DEVELOPER,
    _TESTER,
    _REVIEWER,
)

_ROLES: dict[str, AgentRoleSpec] = {spec.code: spec for spec in _ROLE_LIST}

# 未知角色回退到统筹，保证调用方不会因缺角色而中断。
_FALLBACK_ROLE = _COORDINATOR


def all_roles() -> tuple[AgentRoleSpec, ...]:
    return _ROLE_LIST


def get_role_spec(code: str) -> AgentRoleSpec:
    """取角色定义；未知角色回退到统筹角色。"""
    return _ROLES.get(code, _FALLBACK_ROLE)


def role_tool_names(code: str) -> frozenset[str]:
    """该角色允许使用的工具名集合。"""
    return get_role_spec(code).toolset


def role_write_target(code: str) -> str:
    """该角色的产物写入目标目录（code / tests / docs），无写权限时为空串。"""
    return get_role_spec(code).write_target


def role_system_fragment(code: str) -> str:
    """拼装注入到系统提示词中的角色说明。"""
    spec = get_role_spec(code)
    lines = [
        f"你是本项目的{spec.name}。{spec.duty}",
        f"输出契约：{spec.output_contract}",
        "可用工具：" + "、".join(sorted(spec.toolset)) + "。",
        "你只能使用上述工具，越权的工具调用会被直接拒绝。",
    ]
    lines.extend(spec.extra_rules)
    return "\n".join(lines)
