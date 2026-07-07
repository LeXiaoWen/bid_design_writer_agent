# PRD：建筑设计标书方案助手 v1.0

## 1. 产品概述

**建筑设计标书方案助手**是一个本地桌面 AI 工作台，面向建筑设计公司的投标团队。用户上传招标文件后，系统通过两阶段 AI 工作流自动提取关键信息并生成完整的设计标书方案。

### 1.1 核心价值

- 将数小时的招标文件研读缩短到分钟级的信息提取。
- 标准化标书方案输出（设计方案、绘图提示词、图纸清单、制作规范）。
- 支持多家 AI 模型供应商，用户可选择性价比最优的模型。
- 本地运行，招标文件和 API key 不经过第三方服务器。

### 1.2 产品形态

跨平台桌面应用（macOS / Windows / Linux），双击启动，无需命令行操作。

---

## 2. 功能列表

### 2.1 用户认证

- 首次启动创建本机账号（用户名 + 密码，Argon2id 哈希存储）。
- 后续启动需登录，会话 8 小时有效。
- 支持修改密码和退出登录。
- 关闭窗口后自动注销。

### 2.2 模型配置

- 内置 6 种 Provider 预设：OpenAI、DeepSeek、通义千问 DashScope、SiliconFlow、OpenRouter、自定义。
- 支持填入 API key（保存到系统钥匙串，不写入数据库）。
- 支持从远程端点拉取可用模型列表。
- 一个 Provider Profile 可被多个对话和标书工作流复用。

### 2.3 通用聊天

- SSE 流式输出，打字机效果。
- Markdown 渲染（react-markdown + remark-gfm）。
- 支持停止生成（已输出内容保存为 interrupted）。
- 对话归属项目，消息持久化在本地 SQLite。

### 2.4 标书两阶段工作流

**阶段一 — 信息提取**：
- 上传 PDF / DOCX / TXT / MD 招标文件，自动解析文本。
- 调用 AI 提取四类关键信息：项目概况、评分标准、工期与预算、暗标规范。
- 结果以 Markdown 呈现，用户可在聊天中确认或指出修正内容。

**阶段二 — 方案生成**：
- 确认阶段一后选择模板：
  - **12 章设计标**：完整技术标结构。
  - **5 章全过程咨询标**：咨询类标书结构。
  - **自动判断**：AI 根据招标文件内容自行选择合适的目录结构。
- 调用 AI 生成完整设计方案、绘图提示词 + 专业图纸需求清单、标书制作规范。
- 成果以 4 个 Markdown 文件呈现，支持单文件下载和 ZIP 打包。

### 2.5 项目管理

- 项目 → 对话 → 消息 三层结构。
- 支持创建/重命名/删除项目和对话。
- FTS5 全文搜索：搜索项目标题、对话标题、消息内容。
- 侧边栏可折叠，折叠态仅显示图标。

### 2.6 行为摘要

- 阶段二生成完成后，自动提取「用户行为与需求摘要」并保存到本机应用数据目录。
- 保存失败不影响成果下载。
- 不发送邮件，不上传原始招标文件、上传原文件或完整聊天记录。

---

## 3. 用户流程

```text
首次启动 → 注册账号 → 登录
后续启动 → 登录
        ↓
  进入 Codex 工作台
        ├── 左侧：项目列表 / 对话历史 / 搜索 / 模型配置 / 用户面板
        └── 右侧：聊天窗口 + 标书工作流面板
        ↓
  配置模型（选择 Provider + 填入 API key）
        ↓
  创建项目 → 创建对话 → 上传招标文件
        ↓
  阶段一：提取 → AI 返回结果 → 用户确认或修正
        ↓
  阶段二：选择模板 → AI 生成方案 → 预览 + 下载
        ↓
  本地保存行为摘要
```

---

## 4. 技术架构

### 4.1 整体架构

```text
Electron Desktop Shell
  │
  ├── 开发模式：加载 http://localhost:3000（Next.js dev server）
  └── 打包模式：加载 app://frontend/index.html（Next.js 静态导出）
        │
Next.js 前端（React 19, Tailwind CSS 4, TypeScript）
  ├── 单页应用（page.tsx）
  ├── Codex 式双栏布局：侧边栏 + 聊天区
  ├── 自定义 SSE 解析与 chatReducer 状态管理
  └── 通过 fetch + SSE 调用后端 REST API
        │
        │ HTTP (127.0.0.1:8765)
        │
FastAPI 后端（Python 3.10+, Uvicorn）
  ├── /api/v1/* 业务接口（项目/对话/消息/搜索/标书工作流/聊天/模型配置/认证）
  ├── 中间件：CORS + APP_AUTH_SECRET + Bearer Token
  └── 业务服务层（backend/services/）
        │
SQLite 数据库（WAL 模式，FTS5 全文搜索）
  ├── users, auth_sessions
  ├── projects, conversations, messages
  ├── provider_profiles
  └── bid_workflows, bid_artifacts
```

### 4.2 前端

| 项目 | 选型 |
| --- | --- |
| 框架 | Next.js 16 (App Router) |
| UI 库 | React 19 |
| 样式 | Tailwind CSS 4 + PostCSS |
| 语言 | TypeScript 5 |
| 图标 | lucide-react |
| Markdown 渲染 | react-markdown + remark-gfm |

**组件结构**：

| 文件 | 职责 |
| --- | --- |
| `page.tsx` | 主页面：认证流程、侧边栏、聊天窗口、标书工作流面板、模型配置面板 |
| `WorkbenchLayout.tsx` | 双栏布局容器（可折叠侧边栏 + 主内容区） |
| `ToolReasoning.tsx` | 工作流执行状态展示 |
| `MarkdownPane.tsx` | Markdown 内容渲染 |
| `api.ts` | API 调用层：auth header 注入、SSE 流式解析、文件上传/下载 |
| `chatReducer.ts` | 聊天消息状态机（message_start → delta → message_done） |
| `types.ts` | TypeScript 类型定义 |

### 4.3 后端

| 项目 | 选型 |
| --- | --- |
| 框架 | FastAPI |
| 服务器 | Uvicorn (ASGI) |
| 数据校验 | Pydantic v2 |
| 文档解析 | PyPDF2 + python-docx |
| AI 调用 | openai SDK（OpenAI-compatible） |
| 密码哈希 | argon2-cffi (Argon2id) |
| 凭据存储 | keyring（系统钥匙串） |

**服务模块**（`backend/services/`）：

| 模块 | 职责 |
| --- | --- |
| `document_parser.py` | PDF/DOCX/TXT/MD 文本解析，含错误处理 |
| `skill_loader.py` | 加载标书 Skill 指令，构建各阶段 system prompt |
| `llm.py` | OpenAI-compatible SDK 封装，统一 role 映射 |
| `artifacts.py` | 成果文件拆分、命名、ZIP 打包 |
| `auth.py` | 用户注册/登录/登出/改密，session 管理 |
| `workbench_store.py` | SQLite 数据库操作，FTS5 搜索，keyring 集成 |
| `workbench_llm.py` | SSE 流式聊天与取消 |
| `behavior_report.py` | 行为摘要提取与本地保存 |
| `config.py` | API Provider 预设管理 |
| `provider_models.py` | 远程模型列表拉取 |

### 4.4 桌面壳

| 项目 | 选型 |
| --- | --- |
| 框架 | Electron 39 |
| 语言 | TypeScript 5 |
| 打包 | electron-builder |

**主进程职责**：

- 创建 BrowserWindow（默认 1440×960，最小 1180×760）。
- 启动 FastAPI 后端进程（开发模式用 uvicorn，打包模式用 PyInstaller 可执行文件）。
- 生成 `APP_AUTH_SECRET` 随机密钥并注入后端。
- 注册 `app://` 自定义协议，加载打包后的静态前端。
- preload 通过 IPC 暴露 `auth:get-app-secret` 和 `workspace:select-directory`。

### 4.5 数据存储

| 项目 | 选型 |
| --- | --- |
| 数据库 | SQLite（WAL 模式） |
| 全文搜索 | FTS5 |
| 数据库路径 | `.data/app.db`（可通过 `AI_WORKBENCH_DATA_DIR` 配置） |

**数据库表**：

| 表 | 说明 |
| --- | --- |
| `users` | 用户（id, username, password_hash, created_at, updated_at, last_login_at） |
| `auth_sessions` | 登录会话（token_hash, user_id, expires_at） |
| `projects` | 项目 |
| `conversations` | 对话（含关联的 provider_profile_id 和 model） |
| `messages` | 消息（role, content, status, model, usage） |
| `messages_fts` | FTS5 全文索引 |
| `provider_profiles` | 模型配置（不含 API key 明文） |
| `bid_workflows` | 标书工作流（状态、阶段一/二结果、模板选择） |
| `bid_artifacts` | 成果文件（文件名、内容、大小、类型） |

### 4.6 打包分发

```text
Next.js 静态导出 (frontend/out/)
        +
Electron 编译 (.desktop-dist/)
        +
PyInstaller 后端可执行文件 (.agent-dist/ai-workbench-agent)
        ↓
electron-builder → release/
  ├── macOS: 建筑设计标书方案助手-0.1.0-mac.zip
  ├── Windows: .exe / .zip
  └── Linux: .AppImage / .tar.gz
```

PyInstaller 打包流程：创建隔离的 `.agent-venv` 虚拟环境 → 安装 `requirements-agent.txt` 依赖 → PyInstaller 编译为单一可执行文件。目标机器无需安装 Python。

---

## 5. OpenAI 兼容配置

### 5.1 内置预设

| Provider | Base URL | 默认模型 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 通义千问 DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` |
| 自定义 | 用户填写 | 用户填写 |

### 5.2 兼容策略

- 使用 OpenAI-compatible Chat Completions 协议。
- 系统指令统一使用 `system` role（国产兼容接口不支持 `developer` role）。
- API key 保存到系统钥匙串，provider profile 响应中不回显。

---

## 6. 文件处理

### 6.1 上传支持

| 格式 | 解析库 | 错误处理 |
| --- | --- | --- |
| `.pdf` | PyPDF2 | 扫描 PDF（无文本层）→ 提示先 OCR |
| `.docx` | python-docx | 损坏文件 → 返回解析失败原因 |
| `.txt` | 内置 `open()` | 空文件 → 提示为空 |
| `.md` | 内置 `open()` | 同上 |

`.doc` 格式不支持，提示用户转换为 `.docx`。

### 6.2 成果文件

阶段二完成后生成 4 个 Markdown 文件：

| 文件 | 内容 |
| --- | --- |
| `{项目名称}_招标文件信息提取.md` | 阶段一完整提取结果 |
| `{项目名称}_设计方案.md` | 阶段二完整设计方案 |
| `{项目名称}_绘图提示词_图纸需求清单.md` | 效果图提示词 + 专业图纸清单 |
| `{项目名称}_标书制作规范.md` | 封面、字体、份数、暗标等排版要求 |

项目名称从阶段一提取结果中自动推断，非法文件名字符自动移除。未识别时默认使用「设计标书」。

### 6.3 大文件处理

招标文件超过 120,000 字符时自动截断，并提示用户「文本过长，已截断。请优先基于已有内容提取，并提示用户可补充缺失页」。

---

## 7. 安全设计

### 7.1 本机访问控制

```
请求 /api/v1/* 业务接口
  │
  ├── 第一层：X-App-Auth-Secret header
  │   ├── 由 Electron 启动时生成（randomBytes 32）
  │   ├── 前端通过 preload IPC 获取并附加到请求
  │   ├── 后端与 APP_AUTH_SECRET 环境变量比对
  │   └── 不匹配 → 403
  │
  └── 第二层：Authorization: Bearer <token>
      ├── 登录/注册后返回
      ├── SHA-256 哈希存储，8 小时过期
      ├── 公开端点（/auth/status, /auth/setup, /auth/login）免校验
      └── 无效或过期 → 401
```

开发模式下 `APP_AUTH_SECRET` 为空时跳过第一层，方便浏览器调试。

### 7.2 API Key 保护

- 使用 Python `keyring` 库写入系统钥匙串（macOS Keychain / Windows Credential Manager）。
- SQLite 中仅存储 `credential_key`（UUID），不回显或存储 API key 明文。
- keyring 不可用时：生产模式返回错误；设 `AI_WORKBENCH_ALLOW_MEMORY_CREDENTIALS=true` 时回退到进程内存（仅开发/测试）。

### 7.3 安全边界

**防护目标**：
- 防止未登录访问项目、对话、招标文本、成果文件和模型配置。
- 防止普通网页在不知道 `APP_AUTH_SECRET` 的情况下调用本地 API。
- 防止模型 API key 明文落入 SQLite。

**不防护**：
- 本机管理员或恶意进程直接读取 SQLite 文件。
- 屏幕录制、键盘记录。
- 用户主动导出的文件外泄。

**V1 不做**：
- 全库加密。
- 团队多用户、权限分级、云端同步、企业 SSO。

---

## 8. 标书工作流状态机

| 状态 | 含义 | 可执行操作 |
| --- | --- | --- |
| `uploaded` | 文件已上传并解析 | 开始阶段一提取 |
| `extracting` | 阶段一提取中 | 可取消 |
| `extraction_ready` | 阶段一完成，等待确认 | 确认或修正 |
| `generating` | 阶段二生成中 | 可取消 |
| `completed` | 成果已生成 | 预览、下载 |
| `failed` | 执行失败 | 查看错误信息，重新操作 |
| `cancelled` | 已取消 | 可从头重新开始 |

---

## 9. API 端点

### 9.1 认证

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/api/v1/auth/status` | 获取认证状态 |
| POST | `/api/v1/auth/setup` | 创建本机账号 |
| POST | `/api/v1/auth/login` | 登录 |
| POST | `/api/v1/auth/logout` | 登出 |
| GET | `/api/v1/me` | 当前用户信息 |
| POST | `/api/v1/auth/change-password` | 修改密码 |

### 9.2 业务

| Method | Path | 说明 |
| --- | --- | --- |
| GET/POST/PATCH/DELETE | `/api/v1/projects` | 项目 CRUD |
| GET/POST/PATCH/DELETE | `/api/v1/conversations` | 对话 CRUD |
| GET | `/api/v1/conversations/{id}/messages` | 消息列表 |
| GET/POST/PATCH/DELETE | `/api/v1/provider-profiles` | 模型配置 CRUD |
| GET | `/api/v1/provider-profiles/{id}/models` | 远程模型列表 |
| GET | `/api/v1/search?q=...` | FTS5 全文搜索 |
| POST | `/api/v1/chat/stream` | SSE 流式聊天 |
| POST | `/api/v1/chat/{run_id}/cancel` | 停止生成 |

### 9.3 标书工作流

| Method | Path | 说明 |
| --- | --- | --- |
| POST | `/api/v1/bid-workflows` | 创建并上传文件 |
| GET | `/api/v1/bid-workflows` | 工作流列表 |
| GET | `/api/v1/bid-workflows/{id}` | 工作流详情 |
| POST | `/api/v1/bid-workflows/{id}/extract` | 阶段一提取 |
| POST | `/api/v1/bid-workflows/{id}/confirm` | 确认阶段一 |
| POST | `/api/v1/bid-workflows/{id}/generate` | 阶段二生成 |
| POST | `/api/v1/bid-workflows/{id}/cancel` | 取消工作流 |
| GET | `/api/v1/bid-workflows/{id}/artifacts` | 成果列表 |
| GET | `/api/v1/bid-workflows/{id}/artifacts/{name}` | 下载单个成果 |
| GET | `/api/v1/bid-workflows/{id}/export.zip` | 下载成果 ZIP |
---

## 10. 开发与构建

### 10.1 本地开发

```bash
# 安装
python3 -m pip install -r backend/requirements.txt
npm install
npm --prefix frontend install

# 启动（同时运行 UI + 后端 + Electron）
npm run dev

# 分步启动
npm run dev:ui       # Next.js → localhost:3000
npm run dev:agent    # FastAPI → 127.0.0.1:8765

# 验证
npm run test:backend   # pytest
npm run test:frontend  # Node test
npm run typecheck      # TypeScript 类型检查
npm run build          # 全量构建检查
```

### 10.2 打包

```bash
npm run pack         # 未压缩应用目录（快速验收）
npm run dist         # 当前平台安装包
npm run dist:mac     # macOS .zip
npm run dist:win     # Windows .exe
npm run dist:linux   # Linux AppImage
```

产物输出到 `release/`。

---

## 11. 已知限制

- 未配置代码签名、公证、自动更新。
- 不做团队多用户、权限分级、云端同步。
- 不做全库加密。忘记密码需手动操作 SQLite。
- 不做 OCR（扫描 PDF 需用户先 OCR 提取文本层）。
- 不做 Word `.docx` 成果导出（成果为 Markdown 格式）。
- 大型招标文件超过 120K 字符会截断。
- 不接入 Gemini/Claude 原生协议（可通过 OpenRouter 使用）。
- 首次注册页未展示隐私说明。
