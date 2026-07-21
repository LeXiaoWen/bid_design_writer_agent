# 建筑设计标书方案助手

本地运行的跨平台桌面应用，用于管理 LLM 对话、解析招标文件并生成建筑设计技术标书。

**技术栈：** Electron · Next.js (Turbopack) · FastAPI · SQLite

## 主要功能

### 多账号工作台

本机注册多个独立账号，每个账号拥有自己的项目、对话历史、模型配置和标书生成记录。切换账号不互相干扰，跨账号资源访问返回 404。登录会话有效期 8 小时，退出或修改密码后旧会话立即失效。

### 模型配置

支持所有 OpenAI-compatible API 提供商，包括 DeepSeek、OpenAI、通义千问、硅基流动、OpenRouter 等，也可填入任意自定义 API 地址。每个模型配置独立填写 Base URL、模型名称、API key，每个账号可管理多个模型配置并在对话中随时切换。API key 使用登录密码派生的 AES-GCM 密钥加密后存于本地 SQLite，退出登录后必须重新输入密码才能解密使用。

### 项目与对话

- **默认项目** — 注册后自动创建，所有未指定项目的对话均存放于此
- **文件夹项目** — 选择本地文件夹创建项目，仅记录工作目录路径，不复制或上传文件内容。适合按项目组织对话
- 对话支持创建、重命名、切换、删除，消息按会话分组存储

### 标书生成（两阶段）

| 阶段 | 操作 | 说明 |
|------|------|------|
| 阶段一 | 上传招标文件 → 信息提取 | 系统自动提取项目信息、技术要求、评分标准、成果要求，生成结构化摘要供核对 |
| 阶段二 | 确认信息 → 生成方案 | 核对并补充提取结果后，按招标约束动态生成设计方案标书，支持下载 Markdown 或 ZIP |

每个阶段以流式方式输出，可随时中止。确认阶段一信息时可手动补充额外说明，影响阶段二的生成方向。

### 聊天与 Markdown 渲染

- 流式 SSE 响应，支持随时中止生成
- Markdown 完整渲染：标题层级、表格、代码块（语法高亮）、引用、列表
- 代码块采用半透明主题感知背景，带左侧强调色条
- 消息按会话分组，切换对话保留完整上下文

### 联网搜索

集成 Tavily Search API。在「模型配置」中保存 Tavily API key 后，对话输入区开启「联网搜索」开关，模型将获得实时搜索结果作为上下文补充。未开启时普通对话不受影响。也支持通过 `TAVILY_API_KEY` 环境变量设置全局 fallback key。

### 主题系统

- **4 套内置默认背景**（夏日、日落、晚霞、海边），首次进入自动随机激活一款
- **自定义上传** — 支持 PNG、JPEG、WebP（最大 16 MB），自动校验格式与尺寸
- **智能调色板** — 根据背景图主色调自动生成界面配色
- 可设置亮色/暗色/自动外观模式
- 默认图片目录可通过 `AI_WORKBENCH_IMAGES_DIR` 环境变量自定义

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
TAVILY_SEARCH_DEPTH=basic
WEB_SEARCH_MAX_RESULTS=5

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

未签名 macOS 应用首次打开需在 Finder 中右键选择「打开」。正式发布建议配置 Apple 签名与公证。

## 数据与安全

- 密码使用 Argon2 哈希，不存明文
- API key 用登录密码派生的 AES-GCM 密钥加密存于本地 SQLite，仅在登录后的内存中解密
- 退出登录或后端重启后必须重新登录才能使用已保存密钥
- 所有数据按账号隔离，接口不返回其他账号的信息

**数据目录：**

| 平台 | 路径 |
|------|------|
| macOS | `~/Library/Application Support/bid-design-writer-desktop/data/` |
| Windows | `%APPDATA%\bid-design-writer-desktop\data\` |

## 验证

```bash
npm run check:version   # 版本一致性检查
npm run test:backend    # 后端测试
npm run typecheck       # TypeScript 类型检查
```

## 项目结构

```text
backend/                  FastAPI、SQLite、流式聊天与标书 workflow
backend/bundled_skills/   内置 bid-design-writer skill 资源
frontend/                 Next.js 工作台界面
desktop/                  Electron 主进程
images/                   默认主题背景图（打包时自动捆绑）
packaging/                PyInstaller spec 与应用图标
scripts/                  构建与打包脚本
release/                  构建产物
```
