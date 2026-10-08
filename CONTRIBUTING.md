# 贡献指南

感谢你考虑为 SDLC Agent 做贡献！本文说明本地开发、提交规范与 PR 流程。

## 开发环境

```powershell
# 后端
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 前端
cd ..\frontend
npm install
```

一键启动前后端：

```powershell
.\scripts\dev.ps1
```

- 后端 http://127.0.0.1:8000 ｜ 前端 http://127.0.0.1:5173

## 提交前自检

```powershell
# 后端测试（必须全绿）
cd backend; .\.venv\Scripts\Activate.ps1; pytest -q

# 前端类型检查 + 构建（必须通过）
cd frontend; npm run build
```

CI 会在 PR 上自动执行以上两项。

## 提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/) 前缀：

- `feat:` 新功能
- `fix:` 缺陷修复
- `docs:` 文档
- `refactor:` 重构（不改变行为）
- `test:` 测试
- `chore:` 杂项（构建、依赖等）

示例：`feat(ui): 视觉重构为 DeepSeek harness 风格`

## 分支与 PR

1. 从 `main` 切出分支：`git checkout -b feat/your-feature`
2. 保持改动聚焦，一个 PR 解决一件事
3. 补充或更新相关测试与文档
4. 发起 PR，填写模板中的变更说明与自检清单

## 代码风格

- 后端：Python，遵循现有 `services/` 拆分与类型标注风格，新增逻辑配套测试
- 前端：TypeScript + React 函数组件，样式统一走 `src/styles/index.css` 的设计令牌，避免硬编码色值

## 安全相关改动

本项目会执行子进程、生成并运行代码。若改动涉及命令执行、路径处理、Provider 访问限制
（`ALLOW_UNSAFE_COMMANDS`、`ALLOWED_PROVIDER_HOSTS`、`FS_BROWSE_ROOT`）等安全边界，
请在 PR 描述中明确说明影响。
