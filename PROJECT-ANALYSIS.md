# 建筑设计标书方案助手 — 项目梳理文档

> 生成时间：2026-07-16 | 版本：v0.1.2

---

## 一、项目概览

**「建筑设计标书方案助手」** 是一款本地运行的跨平台桌面应用（macOS / Windows / Linux），面向建筑设计行业的投标团队。核心流程为：上传招标文件 → 两阶段 LLM 工作流提取关键信息并生成设计方案标书 → 下载 Markdown 或 ZIP 成果。

- 本地运行，数据不出本机
- 支持 OpenAI-compatible API（DeepSeek、OpenAI、通义千问、硅基流动、OpenRouter、自定义）
- 多本机账号隔离，每个账号独立拥有项目、对话、模型配置和标书成果
- 内置 bid-design-writer Skill 指令与模板资源，普通用户无需额外安装

---

## 二、项目架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    Electron 桌面壳                       │
│  desktop/main.ts  │  desktop/preload.ts                  │
│  - 启动/停止 Python 后端进程                             │
│  - 自定义 app:// 协议加载打包前端                         │
│  - 系统对话框（选择工作目录）                             │
│  - 应用认证密钥传递（x-app-auth-secret）                 │
└───────────────┬─────────────────────────────────────────┘
                │ HTTP (127.0.0.1:8765)
┌───────────────▼─────────────────────────────────────────┐
│                  FastAPI 后端 (Python)                    │
│  backend/main.py  — 路由入口                             │
│  ┌──────────┬──────────┬──────────┬──────────────────┐  │
│  │ 认证模块  │ 数据存储 │ LLM 调用 │ 标书工作流        │  │
│  │ auth.py  │ store.py │ llm.py   │ behavior_report  │  │
│  │          │          │ web_     │ skill_loader     │  │
│  │          │          │ search   │ artifacts        │  │
│  └──────────┴──────────┴──────────┴──────────────────┘  │
│  SQLite (app.db) + FTS5 全文索引                         │
└───────────────┬─────────────────────────────────────────┘
                │ HTTP (127.0.0.1:8765)
┌───────────────▼─────────────────────────────────────────┐
│                Next.js 前端 (React/TS)                    │
│  frontend/src/app/page.tsx  — 单体页面应用               │
│  ┌──────────────┬──────────────┬───────────────────┐    │
│  │ 侧边栏        │ 聊天区        │ 设置/账号弹窗      │    │
│  │ 项目/对话列表  │ MarkdownPane │ 模型配置           │    │
│  │ 搜索          │ 工作流面板   │ 联网搜索配置       │    │
│  │ 可拖拽调整宽度 │ SSE 流式接收 │ 修改密码           │    │
│  └──────────────┴──────────────┴───────────────────┘    │
│  chatReducer.ts — SSE 事件状态管理                       │
└─────────────────────────────────────────────────────────┘
```

---

## 三、功能清单与技术实现

### 3.1 用户认证系统

| 项目 | 详情 |
|------|------|
| **功能描述** | 本机多账号注册/登录，8 小时会话有效期，密码修改，退出登录 |
| **技术实现** | Argon2 密码哈希 (`argon2-cffi`)，SHA-256 令牌哈希，SQLite 存储 `users` + `auth_sessions` 表 |
| **关键文件** | [backend/services/auth.py](backend/services/auth.py) |
| **安全措施** | 登录限流（5 次失败锁 60 秒），旧会话密码修改后全部吊销 |

### 3.2 项目与对话管理

| 项目 | 详情 |
|------|------|
| **功能描述** | CRUD 项目（支持绑定本地文件夹作为工作目录）、CRUD 对话、新建对话默认归属"默认项目" |
| **技术实现** | FastAPI RESTful API + SQLite 外键关联（`projects` → `conversations` → `messages`），级联删除 |
| **关键文件** | [backend/services/workbench_store.py](backend/services/workbench_store.py)（数据层），[backend/main.py](backend/main.py)（路由） |

### 3.3 模型配置管理

| 项目 | 详情 |
|------|------|
| **功能描述** | 增删改查 Provider Profile（API Base URL、模型名、API Key），支持 6 种预设（OpenAI / DeepSeek / 通义千问 / SiliconFlow / OpenRouter / 自定义），动态拉取模型列表 |
| **技术实现** | OpenAI Python SDK `AsyncOpenAI().models.list()` 拉取模型列表，API Key 存储在 SQLite 中（`provider_profiles` 表） |
| **关键文件** | [backend/services/provider_models.py](backend/services/provider_models.py)，[backend/services/config.py](backend/services/config.py) |
| **预设信息** | DeepSeek 默认 `deepseek-v4-flash`，通义千问默认 `qwen-plus` |

### 3.4 LLM 流式聊天

| 项目 | 详情 |
|------|------|
| **功能描述** | 用户输入文本 → SSE 流式返回 LLM 响应 → Markdown 渲染展示；支持中止生成、自动创建对话 |
| **技术实现** | FastAPI `StreamingResponse` + `text/event-stream`，OpenAI Python SDK `AsyncOpenAI` 流式调用，前端通过 `ReadableStream` 读取 SSE 事件 |
| **关键文件** | [backend/services/workbench_llm.py](backend/services/workbench_llm.py)，[frontend/src/lib/api.ts](frontend/src/lib/api.ts)（`streamChat` 函数），[frontend/src/lib/chatReducer.ts](frontend/src/lib/chatReducer.ts)（状态 reducer） |
| **SSE 事件类型** | `message_start` → `delta` → `message_done` / `error` / `warning` |

### 3.5 联网搜索（Tavily）

| 项目 | 详情 |
|------|------|
| **功能描述** | 在聊天中开启联网搜索，Tavily 返回搜索结果作为 System Prompt 上下文注入 LLM；搜索结果来源标注 `[1]`, `[2]` |
| **技术实现** | `httpx.AsyncClient` 调用 Tavily Search API，支持 `basic`/`advanced` 搜索深度，1-10 条结果 |
| **关键文件** | [backend/services/web_search.py](backend/services/web_search.py) |
| **配置优先级** | 用户本地保存的 Key > 环境变量 `TAVILY_API_KEY`（`.env`） |

### 3.6 招标文件解析

| 项目 | 详情 |
|------|------|
| **功能描述** | 上传招标文件（PDF / DOCX / TXT / MD），自动解析文本内容；限制 25MB |
| **技术实现** | `PyPDF2` 解析 PDF（逐页提取），`python-docx` 解析 DOCX（段落 + 表格），纯文本直接解码 |
| **关键文件** | [backend/services/document_parser.py](backend/services/document_parser.py) |
| **异常处理** | PDF 无文本提示可能是扫描件/DOC 提示转换为 DOCX |

### 3.7 标书工作流（核心功能）

| 项目 | 详情 |
|------|------|
| **功能描述** | 两阶段工作流——阶段一：上传招标文件 → LLM 提取四类关键信息（项目基本信息/设计技术要求/评分标准/制作规范）→ 用户确认 → 阶段二：LLM 动态编排目录并生成完整设计方案标书 → 可下载 Markdown/ZIP |
| **技术实现** | FastAPI `BackgroundTasks` 异步执行（`run_bid_extraction_task` / `run_bid_generation_task`），`agno` 框架 Agent 模式调用 LLM，前端轮询工作流状态（1.5 秒间隔） |
| **关键文件** | [backend/main.py](backend/main.py)（路由 + 后台任务），[backend/services/llm.py](backend/services/llm.py)（Agent 创建与运行），[backend/services/skill_loader.py](backend/services/skill_loader.py)（Skill 指令拼接），[backend/bundled_skills/bid_design_writer/SKILL.md](backend/bundled_skills/bid_design_writer/SKILL.md)（Skill 核心指令，542 行） |
| **状态机** | `uploaded` → `extracting` → `extraction_ready` → `generating` → `completed` / `failed` / `cancelled` |
| **约束** | 每个对话最多一个活跃工作流（唯一索引约束） |

### 3.8 成果文件管理

| 项目 | 详情 |
|------|------|
| **功能描述** | 阶段二完成后自动拆分生成多个 Markdown 文件（信息提取/设计方案/图文需求/制作规范），可单独下载或 ZIP 打包下载 |
| **技术实现** | Python `zipfile` 内存压缩，Nginx-style `Content-Disposition` 头，前端 `Blob` 下载 |
| **关键文件** | [backend/services/artifacts.py](backend/services/artifacts.py) |
| **文件命名规则** | `{项目名称}_招标文件信息提取.md` / `{项目名称}_设计方案.md` 等，从阶段一结果中智能提取项目名称 |

### 3.9 用户行为摘要

| 项目 | 详情 |
|------|------|
| **功能描述** | 阶段二完成后自动生成本机「用户行为与需求摘要」，记录用户目标、修正点、格式偏好、卡点、不满意点等，用于后续优化 |
| **技术实现** | 关键词匹配检测不满意表达（"修改/不对/错误/不要/缺少/补充/调整/重新/不满意/不符合"），脱敏处理（API key/邮箱/手机号） |
| **关键文件** | [backend/services/behavior_report.py](backend/services/behavior_report.py) |
| **存储位置** | `{data_dir}/behavior_reports/{user_id}/{workflow_id}/用户行为与需求摘要.md` |

### 3.10 全文搜索

| 项目 | 详情 |
|------|------|
| **功能描述** | 侧边栏全局搜索项目名、对话标题和消息内容 |
| **技术实现** | SQLite FTS5 虚拟表（`search_index`），支持分词匹配 + LIKE 降级兜底 |
| **关键文件** | [backend/services/workbench_store.py](backend/services/workbench_store.py)（`search` 方法，第 972-1011 行） |

### 3.11 桌面端集成

| 项目 | 详情 |
|------|------|
| **功能描述** | Electron 壳启动 Python 后端（开发模式 uvicorn / 打包模式 PyInstaller 可执行文件），自动分配端口，健康检查等待就绪 |
| **技术实现** | `child_process.spawn`，`app://` 自定义协议加载打包前端，`contextBridge` 安全暴露 IPC API |
| **关键文件** | [desktop/main.ts](desktop/main.ts)，[desktop/preload.ts](desktop/preload.ts) |
| **打包** | PyInstaller（agent.spec）+ electron-builder → macOS .app/DMG、Windows NSIS/ZIP、Linux AppImage |

### 3.12 前端 UI

| 项目 | 详情 |
|------|------|
| **功能描述** | 侧边栏（项目列表/对话历史/搜索）+ 聊天区（消息列表/输入框/工作流面板）+ 弹窗（模型配置/用户账号） |
| **技术实现** | Next.js App Router + React 客户端组件（`"use client"`），纯 CSS 无第三方 UI 库，`lucide-react` 图标，`react-markdown` 渲染 LLM 输出 |
| **关键文件** | [frontend/src/app/page.tsx](frontend/src/app/page.tsx)（主页面，1731 行），[frontend/src/components/MarkdownPane.tsx](frontend/src/components/MarkdownPane.tsx) |

---

## 四、技术栈总览

| 层级 | 技术 | 用途 |
|------|------|------|
| **桌面壳** | Electron 39 + TypeScript | 跨平台桌面容器、系统集成 |
| **后端框架** | FastAPI (Python 3.12) | RESTful API、SSE 流式响应、后台任务 |
| **数据库** | SQLite 3 + FTS5 | 本地持久化、全文搜索 |
| **LLM Agent** | agno 2.6 (原 phidata) | Agent 框架，封装 OpenAI-compatible 模型调用 |
| **LLM SDK** | openai (Python) / AsyncOpenAI | 流式聊天补全、模型列表拉取 |
| **文档解析** | PyPDF2, python-docx | PDF/DOCX 文本提取 |
| **密码安全** | argon2-cffi | Argon2 密码哈希 |
| **HTTP 客户端** | httpx | 异步 Tavily API 调用 |
| **前端框架** | Next.js (React 18+) + TypeScript | UI 渲染、SSE 消费 |
| **Markdown** | react-markdown + remark/rehype | LLM 输出渲染（GFM、代码高亮、HTML sanitize） |
| **图标** | lucide-react | SVG 图标库 |
| **打包** | PyInstaller + electron-builder | 后端 agent 二进制、桌面应用安装包 |
| **测试** | pytest（后端）、Jest（前端 chatReducer） | 单元测试 |

---

## 五、改进建议

### 5.1 架构层面

#### 5.1.1 前端架构升级：拆分为组件

**现状**：[frontend/src/app/page.tsx](frontend/src/app/page.tsx) 是 1731 行的单一组件文件，包含所有 UI 逻辑（50+ state 变量）、状态管理和 API 调用。全局样式 [frontend/src/app/globals.css](frontend/src/app/globals.css) 同样约 1820 行。

**问题**：
- 可维护性差：一个文件涵盖认证、项目管理、聊天、标书工作流、模型配置、搜索
- 难以测试：UI 逻辑与业务逻辑耦合
- 团队协作困难：多人修改同一文件容易冲突
- 存在未使用的组件：`ToolReasoning.tsx` 和 `WorkbenchLayout.tsx` 未被任何文件导入，属于死代码

**建议**：
- 将认证逻辑抽取为 `useAuth` hook 和独立的 `<AuthPanel>` 组件
- 将标书工作流抽取为 `useBidWorkflow` hook 和 `<BidWorkflowPanel>` 组件
- 将侧边栏拆分为 `<Sidebar>` → `<ProjectList>` / `<ConversationList>` / `<SearchPanel>`
- 将模型配置弹窗抽取为 `<ModelConfigModal>` 组件
- 引入轻量级状态管理（如 Zustand）管理跨组件共享状态
- 使用 CSS Modules 或组件级样式替代单一 `globals.css`
- 添加 React Error Boundary 包裹主内容区域，防止单点崩溃导致白屏
- 清理未使用的死代码（`ToolReasoning.tsx`、`WorkbenchLayout.tsx`）

#### 5.1.2 后端路由拆分

**现状**：所有 60+ API 路由集中在 [backend/main.py](backend/main.py) 一个文件（624 行）。

**建议**：
- 使用 FastAPI `APIRouter` 按模块拆分为 `routers/auth.py`、`routers/projects.py`、`routers/chat.py`、`routers/bid_workflow.py`
- 提升可读性和可测试性

#### 5.1.3 数据库迁移机制改进

**现状**：使用 `_ensure_column` + `PRAGMA user_version` 手动迁移，逻辑分散在 `_init_schema` 中。

**建议**：
- 引入 Alembic 或自定义迁移 runner（按版本号顺序执行迁移脚本）
- 避免 `ALTER TABLE ADD COLUMN` 的脆弱性（SQLite 不支持 DROP COLUMN 等操作）

### 5.2 功能层面

#### 5.2.1 对话上下文管理优化

**现状**：聊天时将所有历史消息作为上下文发送（[workbench_llm.py:136](backend/services/workbench_llm.py)）。

**问题**：
- 长对话会超出模型上下文窗口
- Token 消耗线性增长

**建议**：
- 实现滑动窗口或智能摘要策略（保留最近 N 轮 + 定期 LLM 摘要）
- 在前端显示当前 Token 使用量
- 支持用户手动清除上下文

#### 5.2.2 标书工作流增强

**现状**：两阶段工作流是串行的、单次性的。

**建议**：
- 支持阶段二生成后**多次修改**（用户指定修改某章节，LLM 仅重写该部分）
- 加入**版本管理**（每次生成保留历史版本，用户可回退）
- 加入**进度回调**（后台任务实时推送进度百分比，而非仅轮询状态）
- 支持**并行处理多个标段**（同一招标文件中多个标段并行提取/生成）

#### 5.2.3 文档解析能力增强

**现状**：仅支持 PDF/DOCX/TXT/MD 的文本提取，PDF 扫描件无法处理。

**建议**：
- 集成 OCR 能力（Tesseract / PaddleOCR 本地部署或 API 服务）
- 支持 `.doc` (旧版 Word) 格式
- 支持 Excel (.xlsx) 表格提取（招标清单/评分表常为 Excel 格式）
- 优化大文件处理（当前截断 120,000 字符，对超长招标文件可能丢失关键信息）

#### 5.2.4 搜索增强

**现状**：FTS5 全文搜索 + LIKE 降级，能力基本够用。

**建议**：
- 搜索结果中加入**上下文预览**（当前仅显示 snippet，可加粗匹配词）
- 支持**按类型筛选**（项目/对话/消息/标书成果）
- 考虑加入向量嵌入（如使用本地 embedding 模型）实现语义搜索

#### 5.2.5 离线/弱网体验

**现状**：LLM 调用依赖外部 API，无网络时聊天功能不可用。

**建议**：
- 支持**本地模型**（通过 Ollama / llama.cpp 等本地推理引擎）
- 在模型配置中加入"本地模型"预设选项

### 5.3 性能与可靠性

#### 5.3.1 数据库连接管理

**现状**：单连接 + 线程锁（`RLock`），[workbench_store.py:62](backend/services/workbench_store.py) `check_same_thread=False`。

**问题**：FastAPI 异步环境下，同步 SQLite 调用可能阻塞事件循环。

**建议**：
- 使用 `asyncio.to_thread()` 或 `run_in_executor` 将同步 DB 操作放入线程池
- 或使用 `aiosqlite` 实现真正的异步数据库访问
- 考虑在并发场景下迁移到 PostgreSQL（如果未来需要服务端部署）

#### 5.3.2 流式响应错误恢复

**现状**：SSE 流中断后前端无自动重连机制。

**建议**：
- 实现 SSE 断线重连（携带 `Last-Event-ID` header）
- 后端支持从指定消息位置恢复流

#### 5.3.3 后台任务可靠性

**现状**：标书工作流使用 FastAPI `BackgroundTasks`，进程退出即丢失。

**建议**：
- 使用持久化任务队列（如 Celery + Redis，或更轻量的 `arq` / `saq`）
- 在应用重启后自动恢复未完成的任务

### 5.4 安全层面

#### 5.4.1 API Key 存储

**现状**：API Key 明文存储在 SQLite 数据库。

**建议**：
- 使用操作系统密钥链（macOS Keychain / Windows Credential Manager / Linux Secret Service）存储敏感密钥
- 或至少使用 `cryptography` 库进行对称加密，密钥派生自用户密码

#### 5.4.2 CSRF 保护

**现状**：依赖 `APP_AUTH_SECRET` header 检查。

**建议**：
- 加入 CSRF Token 机制（双重提交 Cookie 模式）
- 虽然桌面端本地应用攻击面有限，但若未来提供 Web 版需重点考虑

#### 5.4.3 输入校验

**现状**：依赖 Pydantic 模型校验，基本覆盖。

**建议**：
- 对 LLM 输出进行**内容安全过滤**（避免生成不当内容）
- 文件上传增加**MIME 类型校验**（不能仅信任扩展名）

### 5.5 桌面端可靠性

#### 5.5.1 Electron ASAR 路径处理

**现状**：[desktop/main.ts](desktop/main.ts) 打包模式下使用 `app.getAppPath()` 获取路径，ASAR 虚拟路径下使用 `path.dirname()` 做回退。

**问题**：依赖 ASAR 解压行为，跨平台和 Electron 版本一致性存疑。

**建议**：
- 将 PyInstaller agent 可执行文件放在 `extraResources` 而非 ASAR 内
- 使用 `process.resourcesPath` 替代 `app.getAppPath()` 获取资源路径

#### 5.5.2 后端端口竞争

**现状**：Electron 主进程先随机分配端口，再启动后端绑定该端口。

**问题**：分配和绑定之间存在时间窗口，端口可能被其他程序占用。启动失败时前端只能 30 秒超时后才报错。

**建议**：
- 后端启动后通过 stdout 输出实际绑定端口，Electron 监听 stdout 解析端口
- 或使用 Unix Domain Socket 替代 TCP 端口（仅限 macOS/Linux）

#### 5.5.3 密钥链集成

**现状**：API Key 明文存储在 SQLite。环境变量 `AI_WORKBENCH_ALLOW_MEMORY_CREDENTIALS` 暗示曾计划集成操作系统密钥链，但当前未实现。

**建议**：
- 优先实现 macOS Keychain + Windows Credential Manager 集成
- 使用 `keytar` 或 Electron `safeStorage` API 加密敏感密钥

### 5.6 国际化准备

**现状**：所有 UI 文本硬编码中文，无 i18n 框架。

**建议**：
- 引入 `next-intl` 或 `react-i18next` 实现文本与代码分离
- 为潜在的国际市场扩展做准备

### 5.7 开发体验与工程化

#### 5.5.1 类型安全

**现状**：前端和后端的类型定义是**手动同步**的（[frontend/src/lib/types.ts](frontend/src/lib/types.ts) vs [backend/schemas.py](backend/schemas.py)）。

**建议**：
- 从 OpenAPI schema 自动生成前端类型（使用 `openapi-typescript` 等工具，配合 `npm run` 脚本自动同步）
- 或引入 tRPC / GraphQL Codegen 实现端到端类型安全

#### 5.5.2 测试覆盖率

**现状**：后端有基础 API 测试（`test_api.py`），前端有 `chatReducer` 单测（`chatReducer.test.ts`，在 `.test-dist/` 目录）。

**建议**：
- 为核心工作流（标书两阶段）增加集成测试
- 为前端组件增加 React Testing Library 测试
- 添加 Playwright/Cypress E2E 测试（桌面端完整用户旅程）
- 使用 `pytest-cov` / `c8` 生成覆盖率报告

#### 5.5.3 日志与监控

**现状**：后端使用 `print()` 输出（如 `[behavior-report]` 日志），无结构化日志。

**建议**：
- 引入 `loguru` 或 `structlog` 实现结构化日志
- 按级别分类（DEBUG/INFO/WARNING/ERROR）
- 关键操作（工作流开始/完成/失败、LLM 调用耗时）记录可观测指标

#### 5.5.4 构建流水线

**现状**：手动构建和发布（`npm version` → `npm run dist:mac` → `git tag`）。

**建议**：
- 配置 GitHub Actions 自动构建多平台安装包（macOS/Windows/Linux）
- 构建流水线中集成 lint、typecheck、test
- 自动生成 Changelog 和 Release Notes

---

## 六、技术债务清单（优先级排序）

| 优先级 | 条目 | 影响范围 | 建议时间 |
|--------|------|---------|---------|
| 🔴 高 | `page.tsx` 1731 行单体组件 + `globals.css` 1820 行 | 可维护性、测试 | 近期重构 |
| 🔴 高 | 无对话 Token 管理/上下文窗口控制 | 长对话成本、效果 | 近期实现 |
| 🔴 高 | `main.py` 路由全部在一个文件（624 行） | 后端可维护性 | 近期拆分 |
| 🔴 高 | 存在未使用的死代码（`ToolReasoning.tsx`、`WorkbenchLayout.tsx`） | 代码整洁 | 近期清理 |
| 🟡 中 | 后台任务无持久化（进程退出丢失） | 数据可靠性 | 中期规划 |
| 🟡 中 | 同步 SQLite 操作在异步上下文中 | 并发性能 | 中期改造 |
| 🟡 中 | 前端/后端类型手动同步 | 类型安全 | 中期引入代码生成 |
| 🟡 中 | API Key 明文存储，无操作系统密钥链集成 | 安全性 | 中期加密 |
| 🟡 中 | Electron ASAR 路径处理脆弱 | 桌面端稳定性 | 中期修复 |
| 🟡 中 | 后端端口分配存在竞争条件 | 启动可靠性 | 中期优化 |
| 🟡 中 | React 无 Error Boundary | 用户体验 | 近期添加 |
| 🟢 低 | 无结构化日志（后端用 `print()`） | 问题排查 | 远期优化 |
| 🟢 低 | 测试覆盖率不足 | 质量保障 | 远期补充 |
| 🟢 低 | 无 CI/CD 自动构建 | 发布效率 | 远期配置 |
| 🟢 低 | UI 文本硬编码中文，无 i18n 框架 | 国际化 | 远期规划 |

---

## 七、文件结构导航

```
bid_design_writer_agent/
├── backend/
│   ├── main.py                          # FastAPI 路由入口（60+ API，624行）
│   ├── schemas.py                       # Pydantic 数据模型定义
│   ├── services/
│   │   ├── workbench_store.py           # SQLite 数据层（用户/项目/对话/消息/工作流/搜索，1135行）
│   │   ├── workbench_llm.py             # SSE 流式聊天 + 取消机制
│   │   ├── llm.py                       # agno Agent 创建与运行（非流式，标书工作流使用）
│   │   ├── auth.py                      # Argon2 密码认证 + 会话管理
│   │   ├── skill_loader.py              # 内置 Skill 加载 + 指令拼接
│   │   ├── document_parser.py           # PDF/DOCX 文本解析
│   │   ├── web_search.py                # Tavily 联网搜索
│   │   ├── artifacts.py                 # 成果文件拆分 + ZIP 打包
│   │   ├── behavior_report.py           # 用户行为摘要生成
│   │   ├── provider_models.py           # 模型列表拉取
│   │   ├── config.py                    # API 预设 + 阶段标签
│   │   └── app_version.py              # 版本号读取
│   ├── bundled_skills/bid_design_writer/
│   │   ├── SKILL.md                     # 核心 Skill 指令（542行，两阶段工作流完整规范）
│   │   └── references/                  # 参考模板（大纲模板/可复用模块卡/提取清单等）
│   └── tests/
│       ├── test_api.py                  # API 集成测试
│       └── test_services.py             # Service 层单元测试
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx                 # 主页面（1731行单一组件）
│       │   ├── layout.tsx               # 根布局
│       │   └── globals.css              # 全局样式（CSS 变量 + 布局）
│       ├── components/
│       │   ├── MarkdownPane.tsx          # Markdown 渲染组件
│       │   ├── ToolReasoning.tsx         # 工具推理展示
│       │   └── WorkbenchLayout.tsx       # 工作台布局（Chat/工作台双视图）
│       ├── lib/
│       │   ├── api.ts                   # API 客户端（自动重试 + Auth + SSE 解析）
│       │   ├── chatReducer.ts           # SSE 事件状态 reducer
│       │   └── types.ts                 # 前端类型定义
│       └── types/
│           └── desktop.d.ts             # Electron preload 类型声明
├── desktop/
│   ├── main.ts                          # Electron 主进程（309行）
│   ├── preload.ts                       # 安全的 IPC 桥接
│   └── tsconfig.json                    # 桌面端 TS 配置
├── scripts/
│   ├── run-agent.js/sh                  # 开发模式启动后端
│   ├── run-electron.mjs                 # 开发模式启动 Electron
│   ├── build-agent.mjs                  # 构建 Python 后端二进制
│   ├── package-desktop.mjs              # 打包桌面应用
│   └── sync-version.mjs                # 版本同步
├── packaging/
│   ├── agent.spec                       # PyInstaller 配置
│   └── agent_entry.py                   # PyInstaller 入口
└── package.json                         # 项目元数据 + 完整构建脚本
```

---

## 八、总结

该项目是一个功能完整、设计良好的专业桌面应用，核心亮点包括：

1. **清晰的两阶段工作流设计**：阶段一提取 + 确认 → 阶段二生成，Skill.md 规范详尽（542行专业指令）
2. **本地优先的隐私设计**：数据不出本机，多账号隔离，Argon2 密码哈希
3. **灵活的模型接入**：支持 5 种预设 + 自定义 OpenAI-compatible 服务
4. **完善的桌面打包**：macOS/Windows/Linux 三平台支持，PyInstaller + electron-builder

当前阶段的主要改进方向是**前端架构重构**（拆分单体组件）和**工程化建设**（类型安全、测试、CI/CD），以及**核心体验优化**（对话上下文管理、工作流持久化、API Key 安全存储）。

---

## 九、可替换为成熟组件/库的自定义实现

> 本章节梳理当前项目中可以用现有成熟组件或库直接替换的自定义代码，按投入产出比排序。

### 9.1 全局 CSS（1824 行）→ Tailwind CSS

**现状**：项目已安装 `tailwindcss: ^4.0.0`（[frontend/package.json](frontend/package.json)），但[globals.css](frontend/src/app/globals.css) 的 1824 行中约 **82% 是标准工具类模式**（flex 布局、间距、颜色、圆角、文本溢出处理等），没有使用 Tailwind。

**典型替换对照**：

```css
/* 现状 — 自定义 CSS */
.section-label {
  display: flex; align-items: center; gap: 8px;
  color: #94a1aa; font-size: 14px; font-weight: 760;
  padding: 0 6px;
}
.config-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

/* 替换为 Tailwind v4 */
<button className="flex items-center gap-2 text-[#94a1aa] text-sm font-semibold px-1.5">
<div className="grid grid-cols-2 gap-2">
```

**收益**：CSS 从 1824 行降至约 400 行（保留设计 token 变量 + 复杂动画/组件特定样式），开发时无需在 JSX 和 CSS 文件间来回跳转。

**风险**：渐进迁移即可，无需一次性全部替换。建议新组件直接使用 Tailwind，老代码逐步改造。

---

### 9.2 自定义弹窗 → Radix UI Dialog

**现状**：两处弹窗（模型配置 `.config-modal` + 用户面板 `.user-modal`）均为手动实现，涉及 ~120 行 CSS + 手动逻辑：

| 手动实现 | 代码位置 |
|---------|---------|
| Escape 关闭 | `useEffect` + `keydown` 监听，[page.tsx:345-361](frontend/src/app/page.tsx#L345-L361) |
| 背景遮罩点击关闭 | `onClick={() => setConfigOpen(false)}` + 子元素 `stopPropagation` |
| ARIA 属性 | 手动 `role="dialog"`、`aria-modal="true"`、`aria-labelledby` |
| 焦点管理 | **未实现**（关闭后焦点不回退到触发按钮） |
| 滚动锁定 | **未实现**（弹窗打开时背景仍可滚动） |

**替换方案**：

```tsx
// 之前（page.tsx:1553-1660）— ~110 行 JSX + 2 个 useEffect
<div className="config-modal-backdrop" onClick={() => setConfigOpen(false)}>
  <section className="config-modal" role="dialog" aria-modal="true" 
           aria-labelledby="config-modal-title" onClick={(e) => e.stopPropagation()}>
    {/* 内容 */}
  </section>
</div>

// 之后
import * as Dialog from '@radix-ui/react-dialog';

<Dialog.Root open={configOpen} onOpenChange={setConfigOpen}>
  <Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 bg-black/20 grid place-items-center p-6 z-50" />
    <Dialog.Content className="w-[760px] max-h-[760px] rounded-2xl bg-[#f7fbfe] shadow-xl">
      <Dialog.Title className="sr-only">模型与工具配置</Dialog.Title>
      {/* 内容 */}
      <Dialog.Close />
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
```

**收益**：
- 自动焦点陷阱 + 关闭后回退焦点
- 自动 `body` 滚动锁定
- 无障碍完整合规（无需手动 ARIA）
- 消除 ~120 行 CSS + 2 个 `useEffect`

---

### 9.3 自定义弹出菜单 → Radix UI Dropdown Menu / Popover

**现状**：三处自建弹出菜单：

| 菜单 | 对应类名 | 手动处理 |
|------|---------|---------|
| 模型选择列表 | `.model-menu` | `aria-expanded`、点击外部关闭未实现 |
| 文件上传菜单 | `.attachment-menu` | 同上 |
| Provider 选择 | `<select>` 元素 | 原生控件 |

```tsx
// 之前（page.tsx:1109-1131）— 手动一切
{modelMenuOpen && (
  <div className="model-menu">
    {providerModels.map(model => (
      <button className={model.id === currentProfile?.model ? "model-option active" : "model-option"} 
              key={model.id} onClick={() => chooseModel(model.id)}>
        {model.name || model.id}
      </button>
    ))}
  </div>
)}
```

**替换方案**：

```tsx
// 之后 — Radix DropdownMenu
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';

<DropdownMenu.Root>
  <DropdownMenu.Trigger asChild>
    <button className="flex items-center gap-1 max-w-[340px] text-[#383d42] font-semibold truncate">
      {currentProfile?.model ?? "选择模型"}
      <ChevronRight className="data-[state=open]:rotate-90 transition-transform" size={15} />
    </button>
  </DropdownMenu.Trigger>
  <DropdownMenu.Portal>
    <DropdownMenu.Content className="w-[340px] max-h-[300px] overflow-auto ..." side="top" align="end">
      {providerModels.map(model => (
        <DropdownMenu.Item key={model.id} onSelect={() => chooseModel(model.id)}
          className="data-[highlighted]:bg-[#f0f4f6] ...">
          {model.name || model.id}
        </DropdownMenu.Item>
      ))}
    </DropdownMenu.Content>
  </DropdownMenu.Portal>
</DropdownMenu.Root>
```

**收益**：
- 自动键盘导航（↑↓ Enter Escape）
- 点击外部自动关闭
- 碰撞检测自动翻转方向（`side="top"` 空间不够时自动改为 `bottom`）
- Type-ahead 搜索定位
- 消除 ~80 行 CSS

---

### 9.4 数据请求管理 → TanStack Query

**现状**：[page.tsx](frontend/src/app/page.tsx) 中所有 API 调用均为手动 `useState` + `try/catch`，无缓存、无去重、无后台刷新：

| 手动实现 | 代码位置 | 行数 |
|---------|---------|------|
| 项目/对话/消息加载 | `bootstrap()`、`refreshConversations()`、`openConversation()` | ~40 行 |
| 标书工作流轮询 | `useEffect` + `setInterval` 1.5s，[page.tsx:390-408](frontend/src/app/page.tsx#L390-L408) | ~20 行 |
| 搜索防抖 | `useEffect` + `setTimeout` 240ms + `catch`，[page.tsx:374-388](frontend/src/app/page.tsx#L374-L388) | ~15 行 |
| 加载/错误状态 | 50+ `useState` 散落各处 | 分散 |

**替换方案**：

```tsx
// 之前 — 手动轮询工作流（page.tsx:390-408）
useEffect(() => {
  if (!activeBidWorkflow || !["extracting", "generating"].includes(activeBidWorkflow.status)) return;
  const timer = setInterval(async () => {
    try {
      const workflow = await getBidWorkflow(activeBidWorkflow.id);
      setActiveBidWorkflow(workflow);
      setIsBidBusy(["extracting", "generating"].includes(workflow.status));
      if (workflow.conversation_id === currentConversationId) {
        setMessages(await listMessages(workflow.conversation_id));
      }
    } catch (caught) { setError(caught.message); setIsBidBusy(false); }
  }, 1500);
  return () => clearInterval(timer);
}, [activeBidWorkflow, currentConversationId, currentProjectId]);

// 之后 — React Query 自动轮询 + 缓存
const { data: workflow } = useQuery({
  queryKey: ['bidWorkflow', workflowId],
  queryFn: () => getBidWorkflow(workflowId),
  refetchInterval: (query) =>
    ['extracting', 'generating'].includes(query.state.data?.status ?? '') ? 1500 : false,
  enabled: !!workflowId,
});

// 搜索防抖也内置
const { data: searchResults } = useQuery({
  queryKey: ['search', searchQuery],
  queryFn: () => searchWorkbench(searchQuery),
  enabled: searchQuery.trim().length > 0,
  staleTime: 30_000,
});
```

**收益**：
- 自动缓存去重（同一对话切换回来不需要重新加载消息）
- `refetchInterval` 替代手动 `setInterval`
- 内置 `isLoading` / `isError` / `data` 状态
- 离线支持 + 自动重试
- 消除 ~150 行样板代码

---

### 9.5 表单处理 → React Hook Form + Zod

**现状**：三处表单全部手动管理每个字段一个 `useState` + 手动校验：

| 表单 | 手动 state | 手动校验逻辑 |
|------|-----------|------------|
| 认证表单（登录/注册） | `authForm.username`, `.password`, `.confirmPassword` | 空值检查、密码一致性、最小长度 |
| 模型配置表单 | `profileForm.provider`, `.display_name`, `.base_url`, `.model`, `apiKey` | 无客户端校验 |
| 联网搜索配置 | `webSearchForm.api_key`, `.max_results`, `.search_depth` | 无客户端校验 |
| 修改密码 | `passwordForm.currentPassword`, `.newPassword`, `.confirmPassword` | 空值、一致性 |

**替换方案**：

```tsx
// 之前（page.tsx:911-934）— 手动校验
async function submitAuth(event: FormEvent) {
  event.preventDefault();
  if (!username || !authForm.password) { setError("请输入用户名和密码。"); return; }
  if (authMode === "register" && authForm.password !== authForm.confirmPassword) {
    setError("两次输入的密码不一致。"); return;
  }
  // ... 调用 API
}

// 之后 — React Hook Form + Zod
const authSchema = z.discriminatedUnion('mode', [
  z.object({
    mode: z.literal('login'),
    username: z.string().min(1, '请输入用户名'),
    password: z.string().min(1, '请输入密码'),
  }),
  z.object({
    mode: z.literal('register'),
    username: z.string().min(1, '请输入用户名'),
    password: z.string().min(6, '密码至少6位'),
    confirmPassword: z.string(),
  }).refine(d => d.password === d.confirmPassword, { message: '两次密码不一致', path: ['confirmPassword'] }),
]);

const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm({
  resolver: zodResolver(authSchema),
  defaultValues: { mode: 'login', username: '', password: '', confirmPassword: '' },
});

// JSX 中
<input {...register('username')} autoComplete="username" />
{errors.username && <span className="text-[#d34a3a] text-xs">{errors.username.message}</span>}
```

**收益**：
- 声明式校验，Zod schema 可复用于后端类型生成
- 自动 `dirty`/`touching` 状态
- `isSubmitting` 防止重复提交
- 统一的错误展示模式
- 消除 ~80 行手动校验代码

---

### 9.6 错误提示 → Sonner (Toast)

**现状**：自定义 `.error-banner`（~26 行 CSS），固定在顶部居中，无自动消失、无堆叠管理、无交互按钮。

```tsx
// 之前（page.tsx:1476）
{error && <div className="error-banner">{error}</div>}
```

**替换方案**：

```tsx
// 之后 — Sonner
import { toast } from 'sonner';

// 使用
toast.error('请先配置模型 API', {
  action: { label: '配置', onClick: () => setConfigOpen(true) },
  duration: 5000,
});

// 保存成功
toast.success('搜索配置已保存');

// Promise 模式（自动跟踪 pending → success/error）
toast.promise(saveProfile(payload), {
  loading: '保存中...',
  success: '模型配置已保存',
  error: (err) => err.message,
});
```

**收益**：
- 自动消失 + 堆叠管理
- 富交互（操作按钮、Promise 跟踪）
- 四种变体（success/error/info/warning）
- 安装即用，零 CSS 配置

---

### 9.7 侧边栏拖拽 → react-resizable-panels

**现状**：[page.tsx:278-295](frontend/src/app/page.tsx#L278-L295) 约 40 行手动 Pointer Events 实现，手动管理 `pointermove`/`pointerup`、`userSelect`、`cursor` 样式。

```tsx
// 之前（page.tsx:278-295）— 手动 Pointer Events
useEffect(() => {
  if (!isResizingSidebar) return;
  const resizeSidebar = (event: PointerEvent) => {
    setSidebarWidth(Math.min(440, Math.max(250, event.clientX)));
  };
  const stopResizing = () => setIsResizingSidebar(false);
  document.addEventListener("pointermove", resizeSidebar);
  document.addEventListener("pointerup", stopResizing);
  document.body.style.userSelect = "none";
  document.body.style.cursor = "col-resize";
  return () => { /* 清理四个副作用 */ };
}, [isResizingSidebar]);

// 分隔线也有自定义的 ::after 伪元素样式（~16 行 CSS）
```

**替换方案**：

```tsx
// 之后 — 声明式
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';

<PanelGroup direction="horizontal" autoSaveId="sidebar-width">
  <Panel defaultSize={20} minSize={15} maxSize={30}>
    <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(c => !c)} />
  </Panel>
  <PanelResizeHandle className="w-2 hover:bg-gray-300 transition-colors" />
  <Panel>
    <ChatWorkspace />
  </Panel>
</PanelGroup>
```

**收益**：
- 键盘可访问（拖拽手柄支持键盘操作）
- 触屏完美支持
- 像素级精确
- `autoSaveId` 自动持久化宽度到 localStorage
- 消除 ~40 行 effect + ~16 行 CSS

---

### 9.8 标签页切换 → Radix UI Tabs

**现状**：登录/注册切换用自定义 `.auth-tabs`（~27 行 CSS），手动 `role="tablist"`。

**替换方案**：

```tsx
// 之前（page.tsx:1254-1261）
<div className="auth-tabs" role="tablist" aria-label="账号入口">
  <button className={authMode === "login" ? "active" : ""} onClick={() => switchAuthMode("login")}>登录</button>
  <button className={authMode === "register" ? "active" : ""} onClick={() => switchAuthMode("register")}>注册</button>
</div>

// 之后
import * as Tabs from '@radix-ui/react-tabs';

<Tabs.Root value={authMode} onValueChange={(v) => switchAuthMode(v as "login" | "register")}>
  <Tabs.List className="grid grid-cols-2 gap-1 p-1 rounded-xl bg-[#f5f7f8] border">
    <Tabs.Trigger value="login" className="...">登录</Tabs.Trigger>
    <Tabs.Trigger value="register" className="...">注册</Tabs.Trigger>
  </Tabs.List>
</Tabs.Root>
```

---

### 9.9 SSE 流式处理 → 自定义 Hook 封装

**现状**：[api.ts](frontend/src/lib/api.ts) 中 `streamChat` 函数（~50 行）手动管理 `ReadableStream`、`TextDecoder`、buffer 拼接。

**替换方案**：封装为 `useSSEStream` hook 或使用 `@microsoft/fetch-event-source`：

```tsx
// 之后 — 可复用 hook
function useChatStream() {
  const [messages, dispatch] = useReducer(chatReducer, []);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(async (input: ChatInput) => {
    abortRef.current = new AbortController();
    setIsStreaming(true);
    try {
      await streamChat(input, (event) => dispatch(applyChatStreamEvent(event)), abortRef.current.signal);
    } finally {
      setIsStreaming(false);
    }
  }, []);

  const abort = useCallback(() => abortRef.current?.abort(), []);

  return { messages, isStreaming, sendMessage, abort };
}
```

---

### 9.10 消息列表 → 虚拟滚动

**现状**：`.messages` 容器 `overflow: auto`，长对话时所有消息 DOM 节点都在内存中。

**替换方案**：

```tsx
// 之后 — react-virtuoso
import { Virtuoso } from 'react-virtuoso';

<Virtuoso
  className="messages"
  data={messages}
  followOutput="smooth"
  itemContent={(_, msg) => <MessageRow message={msg} />}
  components={{
    Header: () => conversationTitle,
    Footer: () => workflowPanel,
  }}
/>
```

**收益**：数百条消息时渲染性能显著提升，DOM 节点数量恒定。

---

### 9.11 汇总替换优先级

| 优先级 | 替换项 | 影响范围 | 消除代码量 | 工作量 |
|--------|--------|---------|-----------|--------|
| 🔴 最高 | **Radix UI Dialog** 替换自定义弹窗 | ~120 行 CSS + 2 个 `useEffect` + 无障碍合规 | 大 | **30 分钟** |
| 🔴 最高 | **Radix UI DropdownMenu/Popover** 替换弹出菜单 | ~80 行 CSS + 多处手动 ARIA 状态 | 中 | **1 小时** |
| 🟡 高 | **TanStack Query** 替换手动数据管理 | ~150 行样板代码 + 缓存/轮询自动化 | 大 | **2-3 小时** |
| 🟡 高 | **React Hook Form + Zod** 替换表单处理 | ~80 行手动校验 + `useState` | 中 | **1-2 小时** |
| 🟡 高 | **react-resizable-panels** 替换侧边栏拖拽 | ~40 行 Pointer Events + ~16 行 CSS | 小 | **30 分钟** |
| 🟢 中 | **Sonner** 替换错误提示 | 26 行 CSS + 增强交互 | 小 | **15 分钟** |
| 🟢 中 | **Radix UI Tabs** 替换标签页 | 27 行 CSS | 小 | **15 分钟** |
| 🟢 中 | **Tailwind CSS** 逐步替换自定义样式 | 1824 → ~400 行 CSS | 大 | **渐进迁移** |
| 🔵 低 | **react-virtuoso** 虚拟列表 | 性能优化 | 小 | **30 分钟** |
| 🔵 低 | **useSSEStream Hook** 封装 | 可复用性 | 小 | **30 分钟** |

> **建议实施路径**：
> 1. **第一批**（30 分钟~1 小时）：Radix UI Dialog + DropdownMenu + Tabs → 立即获得无障碍合规 + 消除 200+ 行 CSS
> 2. **第二批**（2-4 小时）：TanStack Query + React Hook Form → 消除 230 行样板代码，数据层现代化
> 3. **第三批**（渐进）：Tailwind CSS 迁移（新组件直接用，老组件逐步改）+ Sonner + react-virtuoso
