# 第三方组件与许可

本项目包含或依赖以下第三方组件，其许可与版权归各自作者所有。

## 随仓库分发的资源

### JetBrains Mono

- 用途：界面等宽字体（`frontend/src/assets/fonts/`）
- 许可：SIL Open Font License 1.1
- 版权：Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)

SIL Open Font License 1.1 摘要：允许自由使用、研究、修改与再分发（包括商用），
但再分发时**必须保留本版权与许可声明**，且字体本身不得单独售卖。
完整许可文本见 <https://scripts.sil.org/OFL>。

分发本项目的桌面构建产物时，请一并保留上述声明。

## 运行时依赖

后端（Python）与前端（Node）依赖均为其各自作者发布的开源软件，主要使用 MIT / Apache-2.0 / BSD 类许可。
依赖清单见 `backend/requirements.txt` 与 `frontend/package.json`（含 `package-lock.json`）。
如需生成完整的依赖许可清单，可在对应目录使用第三方工具（如 `pip-licenses`、`license-checker`）。
