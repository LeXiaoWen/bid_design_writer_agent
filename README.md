# 建筑设计标书方案助手

本地运行的跨平台 LLM 工作台，用于管理项目与对话、调用 OpenAI-compatible 模型、联网检索，以及从招标文件生成设计方案标书。技术栈为 Electron、Next.js、FastAPI 和 SQLite。

## 主要能力

- 左侧管理项目、文件夹工作目录、普通对话、搜索、模型和联网搜索配置。
- 支持 OpenAI-compatible API，包括 DeepSeek、OpenAI、通义千问、硅基流动、OpenRouter 和自定义服务；DeepSeek 默认模型为 `deepseek-v4-flash`。
- 右侧支持 Markdown 渲染、流式回答、中止生成、模型切换和 Tavily 联网搜索。
- 上传招标文件后按两阶段完成信息提取、确认和标书方案生成，可下载 Markdown 或 ZIP 成果。
- 内置 `bid-design-writer` 指令与模板资源，普通用户不需要安装 Codex、Claude 或本地 skill。
- 支持同一台电脑上的多个本机账号；每个账号独立拥有项目、对话、模型配置、联网搜索配置和标书成果。

## 使用说明

### 首次使用

1. 打开应用后注册本机账号，注册成功会自动登录并创建“默认项目”。
2. 在左侧“模型配置”中新增模型服务，填写 API Base URL、模型名称和 API key 后保存。
3. 在右侧输入问题开始普通对话，或点击添加按钮并选择“上传招标文件”。

### 项目与对话

- “新对话”始终创建在“默认项目”，显示在左侧“对话”区域。
- 选择本地文件夹后会创建一个文件夹项目；在该项目中产生的对话只显示在该文件夹项目下，不会出现在默认项目或通用“对话”列表。
- 选择文件夹只记录工作目录路径，不会复制或上传文件夹中的内容。

### 标书 workflow

1. 上传招标文件，系统提取项目信息、技术要求、评分点和成果要求。
2. 核对并补充提取结果，按招标文件实际要求确定目录结构。
3. 生成完成后，在对应阶段内容下下载 Markdown 文件或 ZIP 包。

系统会在阶段二完成后在本机生成一份“用户行为与需求摘要”，用于后续优化流程。摘要不包含原始招标文件全文、上传文件或完整聊天记录，不会通过邮件发送，也不在普通界面中展示。

### 联网搜索

联网搜索使用 Tavily。先在左侧“模型配置”的联网搜索区域保存 Tavily API key，再在输入区开启“联网搜索”并发送问题。搜索结果会作为上下文提供给当前模型；未启用时普通聊天不受影响。

## 数据与安全

- 账号只保存用户名和 Argon2 密码哈希，不采集姓名、邮箱、单位等信息。
- 项目、对话、工作流、成果、搜索记录及模型和 Tavily 配置均按当前账号隔离。跨账号访问资源会返回 `404`。
- 登录会话有效期为 8 小时；退出登录或修改密码后，旧会话失效。
- 模型 API key 和 Tavily API key 使用登录密码派生密钥进行 AES-GCM 加密后保存于本地 SQLite；密钥仅在登录后的内存中解锁，接口和界面不会回显密钥。
- 退出登录或后端重启后必须重新登录才能使用已保存密钥。升级旧版明文数据时会生成一次登录密码加密的恢复备份，再清除旧明文；旧版系统钥匙串中的密钥需手动重新填写。
- 这是应用层隔离；项目、对话和成果内容仍保存在本地数据库。需要更强隔离时，应使用不同的系统账号。

桌面版数据目录为 Electron 的 `userData/data`：

- macOS 通常是 `~/Library/Application Support/bid-design-writer-desktop/data/`
- Windows 通常是 `%APPDATA%\\bid-design-writer-desktop\\data\\`
- 浏览器开发模式默认使用项目根目录下的 `.data/`

其中 `app.db` 为本地数据库，行为摘要保存于 `behavior_reports/{user_id}/{workflow_id}/`。升级旧版单账号数据库时，应用会在同目录创建一次 `app.db.pre-multitenant.bak` 备份。

## 开发

### 国内网络环境模板

国内网络环境可先配置 npm 缓存与 Electron 下载镜像，再安装依赖和执行打包。配置只影响本机开发环境，不会写入应用或提交到仓库。

macOS / Linux：

```bash
npm config set registry https://registry.npmmirror.com --global
npm config set cache "$HOME/.npm-cache" --global

# 可加入 ~/.zshrc 或 ~/.bashrc，使安装 Electron 和 electron-builder 时使用镜像
export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
export ELECTRON_BUILDER_BINARIES_MIRROR="https://registry.npmmirror.com/-/binary/electron-builder-binaries/"
```

Windows PowerShell：

```powershell
npm config set registry https://registry.npmmirror.com --global
npm config set cache "D:\\npm-cache" --global

# 写入当前用户环境变量；重新打开终端后生效
[Environment]::SetEnvironmentVariable("ELECTRON_MIRROR", "https://npmmirror.com/mirrors/electron/", "User")
[Environment]::SetEnvironmentVariable("ELECTRON_BUILDER_BINARIES_MIRROR", "https://registry.npmmirror.com/-/binary/electron-builder-binaries/", "User")
```

若镜像不可用，可删除上述 Electron 环境变量并执行 `npm config delete registry --global`，恢复 npm 官方源。Electron 官方支持通过 `ELECTRON_MIRROR` 指定二进制下载镜像。

### 安装依赖

```bash
python3 -m pip install -r backend/requirements.txt
npm ci
npm --prefix frontend ci
```

根目录和 `frontend/` 是两个独立的 Node 依赖目录，两个安装命令都需要执行。执行 `npm run pack:*` 或 `npm run dist:*` 时，如果检测到前端直接依赖缺失，会自动按 `frontend/package-lock.json` 补装一次；正常情况下不会重复安装。

### 启动

```bash
npm run dev
```

该命令会启动 FastAPI、Next.js 和 Electron。浏览器调试可分别执行：

```bash
npm run dev:agent
npm run dev:ui
```

然后访问 `http://127.0.0.1:3000`。

### 可选环境变量

从 `.env.example` 复制为 `.env` 后按需配置：

```env
# Tavily 的全局 fallback；用户在界面保存的 key 优先级更高
TAVILY_API_KEY=
WEB_SEARCH_MAX_RESULTS=5
TAVILY_SEARCH_DEPTH=basic

# 仅用于开发者调试或替换内置 skill；普通用户无需设置
BID_DESIGN_WRITER_SKILL_DIR=
```

`BID_DESIGN_WRITER_SKILL_DIR` 设置后会强制使用外部目录；目录必须包含 `SKILL.md` 和 `references/可复用模块卡片.md`。缺少运行所需文件时后端会报错而不会回退到内置版本。修改内置 skill 后需要重新打包。

## 打包

打包会依次构建静态前端、PyInstaller 后端 agent 和 Electron 应用。先安装根目录及 `frontend` 依赖，再在目标系统执行对应命令：

```bash
# macOS
npm run pack:mac        # release/mac/*.app
npm run dist:mac        # ZIP 和 DMG

# Windows PowerShell 或 CMD
npm run pack:win        # release/win-unpacked/
npm run dist:win        # NSIS 安装包和 ZIP
```

PyInstaller 后端 agent 与操作系统相关，Windows 包必须在 Windows 上构建，macOS 包必须在 macOS 上构建。图标文件位于：

```text
packaging/icons/icon.icns  # macOS
packaging/icons/icon.ico   # Windows
```

未签名的 macOS 应用首次打开可能需要在 Finder 中右键选择“打开”。正式对外发布还需要 Apple 签名与公证；Windows 正式发布建议配置代码签名以减少 SmartScreen 拦截。

## 版本与发布

根目录 `package.json` 的 `version` 是唯一发布版本源：Electron 应用元数据、安装包文件名和后端 `/health` 返回值均以它为准。前端 `package.json` 与两个 lockfile 由 `npm run sync:version` 自动同步，不能单独修改版本。

版本采用 SemVer：修复使用 `patch`，新增兼容功能使用 `minor`，不兼容变更使用 `major`。发布时在目标平台完成构建：

```bash
# 以 0.1.0 -> 0.1.1 为例；不会自动提交或创建 tag
npm version patch --no-git-tag-version
npm run sync:version
npm run check:version

npm run test:backend
npm run test:frontend
npm run typecheck
npm run dist:mac  # Windows 平台改为 npm run dist:win

git add package.json package-lock.json frontend/package.json frontend/package-lock.json backend/
git commit -m "chore(release): v0.1.1"
git tag v0.1.1
git push origin main --follow-tags
```

每次 `pack` 或 `dist` 会自动执行版本同步。现有 `v1.0` Git tag 早于该约定且与当前应用版本不一致，保留为历史记录；后续 tag 必须与根版本完全一致，例如 `v0.1.1`。

## 验证

```bash
npm run check:version
npm run test:backend
npm run test:frontend
npm run typecheck
npm --prefix frontend run build
```

## 项目结构

```text
backend/                 FastAPI、SQLite、流式聊天与标书 workflow
backend/bundled_skills/  内置 bid-design-writer 资源
frontend/                Next.js 工作台界面
desktop/                 Electron 主进程和 preload
packaging/               PyInstaller 与应用图标配置
scripts/                 开发、构建和打包脚本
```
