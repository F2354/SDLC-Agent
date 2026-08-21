# SDLC Agent

基于大语言模型多智能体的软件生命周期制品生成与协作平台，毕业设计 MVP。

## 当前状态

- M0：项目骨架
- M1：注册登录、项目管理、瀑布模型种子数据
- M2：LLM Provider 管理，支持 OpenAI 兼容云服务和 Ollama
- M3：Agent 执行引擎，阶段运行、LangGraph 编排、产物保存
- M4：需求访谈对话、确认生成、评审通过/打回闭环
- 后端 FastAPI 服务，启动时自动建表并填充瀑布模型
- 前端 React + Vite + Tailwind 路由骨架

## 目录结构

```text
SDLC-Agent/
├─ backend/          FastAPI 后端
│  ├─ app/
│  │  ├─ api/        API 路由
│  │  ├─ core/       配置
│  │  ├─ db/         数据库会话
│  │  ├─ models/     数据模型
│  │  ├─ schemas/    Pydantic 模型
│  │  ├─ services/   业务服务
│  │  └─ main.py     应用入口
│  ├─ alembic/       数据库迁移
│  └─ tests/         测试
├─ frontend/         React 前端
│  └─ src/
│     ├─ components/ 组件
│     ├─ lib/        工具
│     └─ pages/      页面
└─ scripts/          开发脚本
```

## 快速开始

### 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

健康检查：http://127.0.0.1:8000/api/health

后端启动时会自动创建数据表并初始化瀑布模型与 agent 角色。

### 前端

```powershell
cd frontend
npm install
npm run dev
```

前端地址：http://127.0.0.1:5173

## 文档

- 软件生命周期智能协作平台-详细设计.md
- 实施计划.md
