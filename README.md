# 建筑设计标书方案助手

Electron + Next.js + FastAPI 的跨平台本地 LLM 客户端。主界面采用 Codex 式工作台：左侧折叠菜单管理项目、历史对话、搜索和模型配置，右侧为 OpenAI-compatible 流式聊天窗口。

## 功能

- Codex 式两栏聊天工作台。
- 项目、会话、消息本地 SQLite 持久化。
- FTS5 搜索项目、历史对话和消息。
- 支持 OpenAI-compatible API：OpenAI、DeepSeek、DashScope、SiliconFlow、OpenRouter、自定义 base URL。
- SSE 流式回答。
- 右侧聊天支持 Tavily 联网搜索：打开输入栏“联网搜索”后，后端先搜索再把结果注入模型上下文。
- 支持停止生成；已输出内容会保存为 interrupted。
- 集成标书设计方案 workflow：上传招标文件后完成阶段一提取、用户确认、阶段二生成 Markdown 成果和 ZIP 包。
- 内置 `bid-design-writer` Skill 指令和模板资源，普通用户无需安装 Codex/Claude skill 即可使用标书 workflow。
- 阶段二完成后自动生成“用户行为与需求摘要”，保存在本机应用数据目录中，用于后续优化 workflow；保存失败不影响成果下载。
- 本机账号登录保护：首次启动创建唯一用户名/密码，后续进入 `/api/v1/*` 业务接口需要登录会话。
- 模型 API key 保存到系统钥匙串，不写入 SQLite；开发/测试可显式启用内存回退。

## 目录结构

```text
bid_design_writer_agent/
├── backend/                 # FastAPI + SQLite + OpenAI-compatible streaming
│   ├── main.py
│   ├── schemas.py
│   ├── bundled_skills/      # 内置 bid-design-writer Skill 资源
│   ├── services/
│   └── tests/
├── frontend/                # Next.js 工作台
│   └── src/
├── desktop/                 # Electron 主进程
├── package.json
└── README.md
```

## 安装

```bash
cd bid_design_writer_agent
python3 -m pip install -r backend/requirements.txt
npm install
npm --prefix frontend install
```

## 开发运行

```bash
npm run dev
```

该命令会同时启动：

- FastAPI backend: `http://127.0.0.1:8765`
- Next.js frontend: `http://127.0.0.1:3000`
- Electron 桌面窗口

如果只想在浏览器中调试：

```bash
npm run dev:agent
npm run dev:ui
```

然后打开 `http://127.0.0.1:3000`。

## 镜像加速（中国大陆用户）

在大陆网络环境下，直接下载 Electron 和 npm 依赖可能较慢或超时。建议在执行 `npm install` 和打包命令前配置镜像源。

### npm 镜像

```bash
# 设置 npm 淘宝镜像（推荐）
npm config set registry https://registry.npmmirror.com

# 或本次生效
npm install --registry=https://registry.npmmirror.com
```

### Electron 镜像

项目已在打包脚本中默认使用 `https://npmmirror.com/mirrors/electron/` 作为 Electron 下载源。如需覆盖，可通过环境变量设置：

**macOS / Linux：**
```bash
export ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
```

**Windows（PowerShell）：**
```powershell
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
```

**Windows（CMD）：**
```cmd
set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
```

### electron-builder 下载镜像

electron-builder 在打包时可能需要下载 NSIS、winCodeSign 等工具。如果下载失败，可设置：

```bash
export ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/
```

### Python pip 镜像

后端依赖安装也建议使用国内镜像：

```bash
# 开发期安装
python3 -m pip install -r backend/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或全局配置
python3 -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

> **注意**：镜像源可能出现同步延迟或临时不可用。如遇到依赖版本找不到的情况，可临时切回官方源重试。

## 构建与打包

当前项目支持 macOS 和 Windows 桌面应用打包。打包链路为：

```text
Next.js static export -> PyInstaller 后端 agent -> electron-builder 桌面安装包
```

开发期验证桌面应用：

```bash
npm run dev
```

只做构建检查，不生成安装包：

```bash
npm run build
```

打包前安装依赖：

```bash
npm install
npm --prefix frontend install
```

后端 agent 会在打包时自动创建 `.agent-venv/`，并从 `backend/requirements-agent.txt` 安装运行时依赖，避免被系统 Python 或 Anaconda 环境中的无关库污染。

Electron 和 electron-builder 镜像配置见上方「镜像加速」章节。打包脚本已默认设置 `ELECTRON_MIRROR`，如仍需覆盖可设置同名环境变量。

生成当前平台安装包：

```bash
npm run dist
```

只生成未压缩应用目录，适合快速验收：

```bash
npm run pack
```

### macOS 打包

在 macOS 上执行：

```bash
npm run pack:mac        # 生成 release/mac/*.app，适合本机快速验收
npm run dist:mac:zip    # 生成 zip 分发包
npm run dist:mac:dmg    # 生成 dmg 安装包
npm run dist:mac        # 同时生成 zip 和 dmg
```

macOS 产物输出示例：

```text
release/mac/建筑设计标书方案助手.app
release/建筑设计标书方案助手-0.1.0-mac-x64.zip
release/建筑设计标书方案助手-0.1.0-mac-x64.dmg
```

第一次双击未签名应用时，macOS 可能拦截。可右键应用选择“打开”。正式外部分发仍需要 Apple Developer ID 签名和 notarization。

### Windows 打包

在 Windows 上执行：

```powershell
npm run pack:win        # 生成 release/win-unpacked，适合本机快速验收
npm run dist:win:nsis   # 生成 NSIS 安装程序
npm run dist:win:zip    # 生成 zip 便携包
npm run dist:win        # 同时生成 NSIS 和 zip
```

Windows 产物输出示例：

```text
release/win-unpacked/
release/建筑设计标书方案助手-0.1.0-win-x64-setup.exe
release/建筑设计标书方案助手-0.1.0-win-x64.zip
```

Windows 构建依赖：

- Node.js 20+
- Python 3.10+，建议安装时勾选 Python Launcher；脚本会优先使用 `py -3`，否则回退到 `python`
- 可用的 C/C++ 运行库环境；如果 PyInstaller 依赖安装失败，先确认 Python 和 pip 可正常运行

注意：Windows 包必须在 Windows 上构建。后端 agent 由 PyInstaller 生成，是平台相关可执行文件；macOS 上强行打 Windows 外壳会把 macOS agent 放入 Windows 包，应用无法运行。如确需调试 Electron 外壳交叉打包，可设置 `ALLOW_CROSS_PLATFORM_PACKAGE=true`，但该产物不能作为可运行安装包分发。

### 图标

应用图标位于：

```text
packaging/icons/icon.icns   # macOS
packaging/icons/icon.ico    # Windows
```

替换图标后重新执行对应平台的 `npm run dist:*` 命令即可。

打包过程会生成这些中间目录，均不进入版本控制：

```text
frontend/out/       # 静态前端
.desktop-dist/      # Electron 主进程编译结果
.agent-dist/        # PyInstaller 后端可执行文件
.agent-build/       # PyInstaller 构建缓存
.agent-venv/        # 后端 agent 打包专用虚拟环境
```

注意：

- macOS 正式分发仍需要开发者证书签名和 notarization；当前配置可生成本地可运行包，但未配置签名。
- Windows 正式分发建议后续补代码签名证书，减少 SmartScreen 拦截。
- packaged 模式会加载内置静态前端，并启动随包分发的本地后端 agent；不再依赖 `localhost:3000`。

## 内置 Skill

应用已内置 `bid-design-writer` 的 `SKILL.md`、阶段一提取清单、标书格式规范和两套目录模板。普通用户不需要在本机安装：

```text
~/.claude/skills/bid-design-writer
~/.cc-switch/skills/bid-design-writer
```

开发者如需调试或替换新版 skill，可显式设置：

```bash
BID_DESIGN_WRITER_SKILL_DIR=/path/to/bid-design-writer npm run dev
```

设置该变量后会强制使用外部 skill 路径；如果外部路径缺少 `SKILL.md` 或 `references/` 中的必要文件，后端会直接报错，不会静默回退到内置版本。修改内置 skill 内容后需要重新执行打包命令，才能进入桌面应用产物。

## 数据目录

Electron 会通过 `AI_WORKBENCH_DATA_DIR` 把应用数据目录传给后端。开发期如果未设置该变量，SQLite 默认写入：

```text
.data/app.db
```

模型 API key 与 Tavily API key 保存在按当前账号隔离的本地 SQLite 数据库中，接口不会回显 key。使用同一个系统账号的人若可直接读取数据库文件，也可读取这些密钥。

## 本机多账号与安全

应用支持同一台电脑注册多个本机账号。用户即租户：项目、对话、标书工作流、成果、搜索记录、模型配置、Tavily 配置和行为摘要均只属于当前登录账号；不支持团队共享、角色权限、云端同步或组织管理。账号只保存用户名和密码哈希，不采集姓名、单位、角色、邮箱等个人信息。密码使用 Argon2 哈希保存，登录会话 token 只保存在前端 `sessionStorage`，退出、关闭会话或修改密码后需要重新登录。

多账号隔离在应用接口和界面层生效。使用同一个 macOS/Windows 系统账号的人若拥有本地文件访问权限，仍可能直接读取应用 SQLite 数据文件；需要更强隔离时，应为每位使用者创建独立的系统账号。

升级已有单用户数据时，应用会在数据库同目录创建 `app.db.pre-multitenant.bak` 备份，并把历史项目、对话、成果和本地配置归属给原有唯一账号；若历史库没有账号，则由第一个成功注册的账号接收。

Electron 桌面端启动后会生成一次性的 `APP_AUTH_SECRET` 并注入本地后端，前端通过 preload 获取后随请求发送。这样即使其他网页知道本地端口，也不能直接调用受保护的 `/api/v1/*` 业务接口。

## 后端接口

新通用客户端接口使用 `/api/v1/*`：

- `GET /api/v1/auth/status`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/change-password`
- `GET /api/v1/me`
- `GET/POST/PATCH/DELETE /api/v1/projects`
- `GET/POST/PATCH/DELETE /api/v1/conversations`
- `GET /api/v1/conversations/{conversation_id}/messages`
- `GET/POST/PATCH/DELETE /api/v1/provider-profiles`
- `POST /api/v1/chat/stream`
- `POST /api/v1/chat/{run_id}/cancel`
- `GET /api/v1/search?q=...`
- `POST /api/v1/bid-workflows/{workflow_id}/cancel`

旧标书助手接口 `/api/projects/*` 已移除，当前应用统一使用 `/api/v1/*`。

## 联网搜索

联网搜索使用 Tavily Search API。可在左侧“模型配置”面板的“联网搜索”区域填写 Tavily API key；保存后 key 会归属当前账号，不会回显到前端。

也可以通过 `.env` 配置作为 fallback：

```env
TAVILY_API_KEY=your_tavily_api_key
WEB_SEARCH_MAX_RESULTS=5
TAVILY_SEARCH_DEPTH=basic
```

使用方式：在右侧聊天输入栏打开“联网搜索”，再发送问题。后端会先调用 Tavily 获取搜索结果，并把标题、URL 和摘要作为上下文交给当前配置的 OpenAI-compatible 模型。未配置 Tavily key 时，开启联网搜索会提示先到左侧配置；关闭该开关时普通聊天不受影响。

桌面打包版会在启动后端前读取 `.env` 并注入环境变量。可用位置包括：

- 开发目录：项目根目录 `.env`
- 打包资源目录：`Contents/Resources/.env`（macOS）或应用资源目录下的 `.env`
- 用户数据目录：macOS 为 `~/Library/Application Support/bid-design-writer-desktop/.env`，Windows 通常为 `%APPDATA%/bid-design-writer-desktop/.env`

修改 `.env` 后需要完全退出应用并重新打开，已启动的后端进程不会自动重新读取配置。

## 行为摘要

阶段二生成完成后，后端会提取本次使用过程中的用户行为和需求，生成 `用户行为与需求摘要.md`，并保存到应用数据目录下的 `behavior_reports/{user_id}/{workflow_id}/`。摘要不会包含原始招标文件全文、上传原文件或完整聊天记录；API key、token、邮箱、手机号等敏感片段会被脱敏。该文件仅本地保存，不发送邮件，也不向普通用户显示发送状态。

## 验证

```bash
npm run test:backend
npm run test:frontend
npm run typecheck
npm --prefix frontend run build
```

## 限制

- V1 已支持本地打包；尚未包含代码签名、公证、自动更新。
- V1 不接入 Gemini/Claude 原生协议；可通过 OpenRouter 或兼容网关使用。
