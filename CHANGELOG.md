# 更新日志

本项目的重要变更记录在此文件。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### Added

- 桌面绿色应用打包：单文件免安装 exe（内置便携 Python 与后端），`scripts/package-portable.ps1`
- 项目级 Agent 配置、MCP Server 配置与工具发现、`SKILL.md` 规则加载
- 过程模型依赖图调度，支持无依赖阶段并行执行
- 运行日志改为 Agent 活动时间线；对话新增「思考过程」折叠面板
- 内置 JetBrains Mono 等宽字体（离线可用）

### Changed

- 界面重构为 DeepSeek harness 视觉风格：单一设计系统、浅色/深色主题、入口页改为任务输入 + 项目列表
- 后端在静态目录存在时直接托管前端，支持单端口运行
- 未检测到 Git 时相关功能优雅降级，不再中断阶段流程

## 里程碑

项目按 M0–M12 推进：项目骨架 → Provider 管理 → Agent 编排 → 评审闭环 → 追溯与导出 →
案例验证 → 可运行代码生成 → 工具化编码 Agent → 编排与实时化 → Agent 内核强化 → 工程化与可观测。
详见 [`实施计划.md`](实施计划.md)。
