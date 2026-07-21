# 建筑设计标书方案助手

本地运行的跨平台桌面应用，用于管理 LLM 对话、解析招标文件并生成建筑设计技术标书。

**技术栈：** Electron · Next.js (Turbopack) · FastAPI · SQLite

## 主要功能

- **多账号工作台** — 本机注册多个账号，项目、对话、模型配置、标书成果按账号隔离
- **模型配置** — 支持 OpenAI-compatible API（DeepSeek、通义千问、硅基流动、OpenRouter 等），每个账号独立管理 API key
- **标书生成** — 上传招标文件 → 提取信息 → 确认目录 → 生成方案，支持下载 Markdown 或 ZIP
- **联网搜索** — 集成 Tavily，搜索结果作为上下文提供给模型
- **主题系统** — 内置 4 套默认背景，支持自定义上传，智能调色板适配
- **Markdown 渲染** — 流式回答、代码高亮、表格展示

## 快速开始

### 环境要求

- Node.js ≥ 20、Python ≥ 3.12
- macOS 或 Windows（打包须在对应平台执行）

### 安装与启动

```bash
python3 -m pip install -r backend/requirements.txt
npm ci && npm --prefix frontend ci
npm run dev
```

浏览器调试可分别启动前后端：

```bash
npm run dev:agent   # FastAPI → http://127.0.0.1:8765
npm run dev:ui      # Next.js → http://127.0.0.1:3000
```

### 国内网络

配置 npm 镜像和 Electron 下载源：

```bash
npm config set registry https://registry.npmmirror.com --global
export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
export ELECTRON_BUILDER_BINARIES_MIRROR="https://registry.npmmirror.com/-/binary/electron-builder-binaries/"
```

## 配置

从 `.env.example` 复制为 `.env` 后按需设置：

```env
# Tavily fallback key（用户在界面保存的 key 优先级更高）
TAVILY_API_KEY=

# 自定义默认主题图片目录（为空则使用内置 images/）
AI_WORKBENCH_IMAGES_DIR=

# 开发者调试内置 skill（普通用户无需设置）
BID_DESIGN_WRITER_SKILL_DIR=
```

## 打包

```bash
npm run dist:mac    # macOS → DMG + ZIP
npm run dist:win    # Windows → NSIS + ZIP
```

未签名 macOS 应用首次打开需在 Finder 中右键选择「打开」。

## 数据与安全

- 密码使用 Argon2 哈希，API key 用登录密码派生的 AES-GCM 密钥加密存于本地 SQLite
- 登录会话有效期 8 小时，退出或改密后旧会话失效
- 跨账号资源访问返回 404

**数据目录：**

| 平台 | 路径 |
|------|------|
| macOS | `~/Library/Application Support/bid-design-writer-desktop/data/` |
| Windows | `%APPDATA%\bid-design-writer-desktop\data\` |

## 验证

```bash
npm run check:version
npm run test:backend
npm run typecheck
```

## 项目结构

```text
backend/                 FastAPI、SQLite、标书 workflow
backend/bundled_skills/  内置 bid-design-writer skill 资源
frontend/                Next.js 工作台界面
desktop/                 Electron 主进程
images/                  默认主题背景图
packaging/               PyInstaller spec 与应用图标
scripts/                 构建与打包脚本
release/                 构建产物
```
