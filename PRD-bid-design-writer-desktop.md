# PRD：设计标书编写助手桌面版

## 1. 背景与目标

### 1.1 背景

`bid-design-writer` Skill 是一个两阶段招标文件解析与设计标书编写工具。项目最初计划从 Streamlit 单文件应用改造为 `Electron + Next.js + FastAPI/Agno` 桌面应用。后续计划进一步调整：基于 `awesome-llm-apps/generative_ui_agents/generative-ui-starter-project` 进行改造，优先复用 Starter 中已经验证过的 CopilotKit、LangGraph、Generative UI、共享 agent state、脚本和前端页面结构。

本 PRD 作为新的对齐版本：目标不再是单纯 REST API 驱动的三栏页面，而是 Chat 驱动的桌面交互工作台。当前项目已经实现的文件解析、Skill 加载、OpenAI-compatible 调用、阶段流程和成果导出代码应作为业务能力复用，不重复开发。

### 1.2 产品目标

将 `bid-design-writer` Skill 包装为一个本地桌面工作台，使设计团队能够通过 Chat 与可视化工作台共同完成：

1. 配置 OpenAI 兼容模型接口。
2. 上传 PDF、DOCX、TXT、MD 招标文件。
3. 执行阶段一信息提取。
4. 在 Chat 中确认、修正或补充提取结果。
5. 选择设计标书模板。
6. 生成设计方案、绘图提示词、专业图纸需求清单和标书制作规范。
7. 在工作台中预览成果并下载 Markdown 或 ZIP。

### 1.3 成功标准

- 用户可以不关心命令行细节，通过桌面窗口完成核心流程。
- 交互方式对齐 Generative UI Starter Project：Chat 为主入口，右侧工作台展示共享状态和成果。
- 当前已实现的业务服务代码可被 LangGraph tools 复用，不重写文件解析、Skill prompt、导出逻辑。
- OpenAI 兼容接口可适配 OpenAI、DeepSeek、DashScope、SiliconFlow 和自定义模型服务。
- 项目结构、脚本命名和本地开发方式尽量贴近 Starter，降低后续复用成本。

## 2. 关键架构决策

### 2.1 新目标方案

推荐默认方案调整为：

```text
Electron Desktop
  ↓ loads
Next.js Frontend + CopilotKit UI
  ↓ /api/copilotkit
CopilotKit Runtime
  ↓
LangGraph Agent Server
  ↓ tools call
Bid Writer Business Services
  ↓
OpenAI-compatible model + bid-design-writer Skill files
```

### 2.2 与上一版方案的变化

| 项目 | 上一版 | 新版 |
| --- | --- | --- |
| 前端交互 | 自研三栏 REST 工作台 | 复用 Starter 的 CopilotKit Chat + 工作台布局 |
| Agent 后端 | FastAPI + Agno Agent | LangGraph agent，工具复用现有业务服务 |
| API 入口 | 多个 REST endpoint | CopilotKit runtime + LangGraph tools 为主，REST 可作为过渡兼容层 |
| 状态同步 | 前端请求项目状态 | 参考 Starter 的 shared agent state，前端和 agent 观察同一项目状态 |
| Generative UI | 暂不引入 | 可选引入 A2UI，用于结构化渲染提取结果、评分矩阵和成果卡片 |
| 代码复用重点 | `ai_negotiation_battle_simulator` FastAPI 模式 | `generative-ui-starter-project` 的页面、hooks、runtime、agent 启动方式 |

### 2.3 过渡原则

- 不整仓覆盖当前项目。
- 不复制演示业务代码，如 todo、flight、sales dashboard、Excalidraw MCP 示例。
- 先复用框架层，再迁移业务流程。
- 当前 `backend/services/*` 是业务核心，应被 LangGraph tools 调用或移动为共享模块。
- Electron 壳继续保留，Starter 没有桌面入口。

## 3. 复用策略

### 3.1 Generative UI Starter Project 复用清单

来源目录：

```text
/Users/leo/Documents/project/vibe-coding/08-ai_tender_agent/awesome-llm-apps/generative_ui_agents/generative-ui-starter-project
```

| Starter 文件/能力 | 复用方式 | 本项目落点 |
| --- | --- | --- |
| `src/app/page.tsx` | 作为 Chat + App 工作台首页结构参考 | `frontend/src/app/page.tsx` |
| `src/components/example-layout/index.tsx` | 复用双模式布局思想，改名为业务工作台布局 | `frontend/src/components/workbench-layout.tsx` |
| `src/components/headless-chat.tsx` | 作为低层 Chat 调用参考 | 必要时用于定制 Chat |
| `src/components/tool-rendering.tsx` | 复用工具执行状态渲染 | `frontend/src/components/tool-rendering.tsx` |
| `src/hooks/use-theme.tsx` | 复用主题 provider | `frontend/src/hooks/use-theme.tsx` |
| `src/app/api/copilotkit/[[...slug]]/route.ts` | 复用 CopilotKit runtime 到 LangGraph 的桥接模式 | `frontend/src/app/api/copilotkit/[[...slug]]/route.ts` |
| `agent/main.py` | 复用 LangGraph agent 入口结构 | `agent/main.py` |
| `agent/pyproject.toml` | 复用 agent Python 依赖管理方式 | `agent/pyproject.toml` |
| `scripts/run-agent.*` | 复用 `langgraph-cli dev --port 8123` 启动方式 | `scripts/run-agent.*` |
| `scripts/setup-agent.*` | 复用 `uv sync` 安装方式 | `scripts/setup-agent.*` |
| A2UI definitions/renderers | 后续用于结构化成果渲染 | V1.1 可引入 |

### 3.2 当前项目业务代码复用清单

| 当前文件 | 保留原因 | 新架构中角色 |
| --- | --- | --- |
| `backend/services/document_parser.py` | 已实现 PDF/DOCX/TXT/MD 解析和错误处理 | LangGraph `parse_tender_file` tool 调用 |
| `backend/services/skill_loader.py` | 已实现 Skill 路径与阶段 instructions 加载 | LangGraph tools 构造阶段一/阶段二 prompt |
| `backend/services/llm.py` | 已修复 OpenAI-compatible role map | 可迁移为 LangChain ChatOpenAI 配置工具，或保留兼容 |
| `backend/services/artifacts.py` | 已实现成果拆分、命名、ZIP | LangGraph `generate_artifacts` / download service 复用 |
| `backend/services/config.py` | 已实现 API preset | 前端配置面板和 agent model 配置复用 |
| `backend/services/project_store.py` | 已实现项目状态雏形 | 迁移为 LangGraph state 或作为过渡 store |
| `desktop/main.ts` | 已实现 Electron 启动和后端探活 | 保留并调整为拉起 UI + LangGraph agent |
| `scripts/run-electron.mjs` | 已适配本机 Electron fallback | 保留 |

### 3.3 不复用或延后复用

- Starter 的 todo 示例组件。
- Starter 的 flight search 示例。
- Starter 的 sales dashboard 示例。
- Starter 的 MCP Excalidraw 示例。
- Starter 的 Open Generative UI sandbox 示例。

这些属于演示业务，不能进入 V1 标书助手主流程。

## 4. 用户与场景

### 4.1 目标用户

- 设计公司投标团队。
- 方案设计师、投标负责人、标书编写人员。
- 需要快速理解招标文件评分标准并产出技术标设计方案的人。

### 4.2 核心场景

| 场景 | 用户目标 | 产品响应 |
| --- | --- | --- |
| 初次处理招标文件 | 快速知道项目要求、评分项和制作规范 | 上传文件后由 agent 调用解析与阶段一提取工具 |
| 信息有误或缺失 | 修改预算、工期、暗标要求等关键信息 | 在 Chat 中输入修正，agent 更新共享项目状态 |
| 进入写作 | 选择合适标书模板并生成正文 | 在 Chat 或工作台中选择模板，agent 调用阶段二生成工具 |
| 交付给设计师 | 提供效果图提示词和专业图纸清单 | 右侧成果面板展示并支持下载 |
| 标书排版 | 确认封面、字体、份数、暗标等要求 | 输出独立标书制作规范文件 |

## 5. 产品范围

### 5.1 V1 范围

- 本地桌面工作台。
- Electron + Next.js + CopilotKit + LangGraph agent。
- 复用当前业务服务完成 PDF、DOCX、TXT、MD 解析。
- OpenAI 兼容 API 配置。
- 单项目本地会话。
- 阶段一信息提取。
- Chat 式确认、修正与补充。
- 模板选择。
- 阶段二生成。
- 成果预览和下载。
- 工具执行状态展示。
- 后端/agent 测试与前端构建验证。

### 5.2 V1 过渡兼容范围

为了降低一次性迁移风险，允许短期保留当前 FastAPI REST 后端：

- REST endpoint 可作为文件上传、成果下载和调试入口。
- LangGraph tools 应优先复用同一套业务函数，而不是通过 HTTP 调 REST。
- 迁移完成后再评估是否移除 REST endpoint。

### 5.3 暂不包含

- 正式安装包、代码签名、自动更新。
- 用户账号、权限和团队协作。
- 历史项目数据库。
- OCR。扫描 PDF 需要用户先 OCR。
- Word `.docx` 成果导出。
- token 级流式输出。V1 使用工具级状态和最终结果回填。
- 多 Agent 编排。
- 引入 Starter 的演示型 todo、flight、dashboard、MCP 示例业务。

## 6. 用户流程

```text
启动桌面应用
  ↓
Electron 拉起 Next.js UI 与 LangGraph agent
  ↓
用户在左侧/顶部配置 OpenAI 兼容 API
  ↓
用户上传招标文件
  ↓
agent 调用 parse_tender_file tool，工作台展示文件状态
  ↓
用户在 Chat 中要求开始提取，或点击开始提取
  ↓
agent 调用 extract_project_info tool
  ↓
工作台展示阶段一提取结果
  ↓
用户在 Chat 中确认或修正
  ↓
agent 更新 confirmed_extraction state
  ↓
用户选择 12 章设计标或 5 章全过程咨询标
  ↓
agent 调用 generate_bid_proposal tool
  ↓
工作台展示成果 tabs
  ↓
下载单个 Markdown 或 ZIP
```

## 7. 信息架构与界面

### 7.1 桌面窗口

- 默认尺寸：`1440 x 960`。
- 最小尺寸：`1180 x 760`。
- 保留 Electron 桌面壳。
- 主界面参考 Starter 的 `ExampleLayout`，但替换为标书业务工作台。

### 7.2 Chat 区

基于 CopilotKit Chat：

- 展示用户消息、agent 回复、工具执行状态。
- 支持建议问题，例如：
  - "开始提取这份招标文件的信息。"
  - "确认阶段一结果。"
  - "预算金额修正为 5000 万元。"
  - "使用 12 章设计标模板生成方案。"
- 使用 `ToolReasoning` 或同类组件展示工具名称、参数摘要和执行状态。

### 7.3 工作台区

工作台展示共享 agent state：

- API 配置状态。
- 文件上传状态。
- 项目阶段。
- Skill 路径状态。
- 阶段一信息提取结果。
- 模板选择。
- 成果文件列表。
- Markdown 成果预览。
- 单文件和 ZIP 下载。

### 7.4 Generative UI 使用边界

V1 不强制要求复杂 A2UI。可优先使用普通 React 工作台和 CopilotKit tool rendering。

V1.1 可将以下内容升级为 A2UI：

- 信息提取结果卡片。
- 评分标准响应矩阵。
- 图纸需求清单。
- 成果文件下载面板。

## 8. Agent State 与 Tools

### 8.1 Agent State

建议 LangGraph state 至少包含：

```python
class BidWriterState(AgentState):
    project_id: str
    stage: str
    api_config: dict
    skill_dir: str
    file_name: str | None
    file_text: str
    extracted_markdown: str
    confirmed_extraction: str
    template_choice: str
    artifacts: dict[str, str]
    last_error: str | None
```

阶段枚举：

| Stage | 含义 | 可执行操作 |
| --- | --- | --- |
| `init` | 新项目，等待配置和上传 | 配置 API、上传文件 |
| `uploaded` | 文件已解析 | 阶段一提取 |
| `confirming` | 阶段一已生成，等待确认或修正 | 确认或修正 |
| `template_select` | 阶段一已确认，等待模板选择 | 选择模板并生成 |
| `generating` | 阶段二生成中 | 等待 |
| `done` | 成果已生成 | 预览和下载 |

### 8.2 Tools

V1 必需 tools：

| Tool | 作用 | 复用代码 |
| --- | --- | --- |
| `get_project_state` | 返回当前项目状态 | `project_store.py` 或 LangGraph state |
| `parse_tender_file` | 解析上传文件 | `document_parser.py` |
| `extract_project_info` | 执行阶段一提取 | `skill_loader.py` + LLM 调用 |
| `revise_extraction` | 根据用户修正更新阶段一结果 | `skill_loader.py` + LLM 调用 |
| `confirm_extraction` | 确认阶段一并进入模板选择 | state update |
| `generate_bid_proposal` | 执行阶段二生成 | `skill_loader.py` + LLM 调用 |
| `list_artifacts` | 返回成果列表 | `artifacts.py` |
| `export_artifacts_zip` | 打包 ZIP | `artifacts.py` |

前端工具可选：

| Frontend tool | 作用 |
| --- | --- |
| `enableWorkbenchMode` | 打开工作台面板 |
| `enableChatMode` | 聚焦 Chat |
| `selectTemplate` | 从 UI 选择模板并同步给 agent |
| `showArtifactTab` | 切换成果 tab |

## 9. OpenAI 兼容配置

内置预设：

| Provider | Base URL | 默认模型 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-v4-pro` |
| 通义千问 DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 硅基流动 SiliconFlow | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3` |
| 自定义 | 用户填写 | 用户填写 |

要求：

- 配置保存在浏览器/Electron 本地 `localStorage`。
- 配置不写入仓库。
- 调用模型时传入 `api_key`、`base_url`、`model`。
- 使用 OpenAI-compatible Chat Completions。
- 对国产兼容接口必须避免发送 `developer` role；系统指令应使用 `system` role。

## 10. 文件上传与成果下载

### 10.1 文件上传

支持格式：

- `.pdf`
- `.docx`
- `.txt`
- `.md`

错误处理：

- 空文件：提示文件为空。
- 扫描 PDF：提示未解析出文本，需要先 OCR。
- 损坏 PDF/DOCX：返回解析失败原因。
- `.doc`：提示转换为 `.docx`。

实现建议：

- V1 可继续使用现有上传 REST endpoint 或 Next.js route 处理二进制文件。
- 文件解析逻辑必须复用 `document_parser.py`。
- 文件文本进入 LangGraph state，供后续 tools 使用。

### 10.2 成果文件

生成文件：

| 文件 | 内容 |
| --- | --- |
| `{项目名称}_招标文件信息提取.md` | 阶段一完整结果 |
| `{项目名称}_设计方案.md` | 阶段二完整设计方案 |
| `{项目名称}_绘图提示词_图纸需求清单.md` | 绘图提示词与专业图纸需求 |
| `{项目名称}_标书制作规范.md` | 标书制作规范 |
| ZIP | 上述全部 Markdown |

文件名规则：

- 优先从阶段一结果中的"项目名称"推断。
- 移除 `\ / : * ? " < > |` 等非法字符。
- 未识别项目名称时使用 `设计标书`。

## 11. 技术架构

### 11.1 Target Architecture

```text
bid_design_writer_agent/
├── agent/                    # LangGraph agent，参考 Starter
│   ├── main.py
│   ├── pyproject.toml
│   └── src/
│       ├── bid_writer_tools.py
│       ├── state.py
│       └── services_bridge.py
├── backend/                  # 业务服务复用层；迁移期可保留 FastAPI
│   ├── main.py
│   ├── schemas.py
│   ├── services/
│   └── tests/
├── frontend/                 # Next.js + CopilotKit
│   ├── src/app/api/copilotkit/[[...slug]]/route.ts
│   ├── src/app/page.tsx
│   ├── src/components/
│   └── src/hooks/
├── desktop/                  # Electron 桌面壳
├── scripts/
└── package.json
```

### 11.2 Frontend

- Next.js App Router。
- React 19。
- CopilotKit React Core/UI。
- 复用 Starter 的 Chat + App layout 模式。
- lucide-react 图标。
- Tailwind 4/PostCSS。
- `react-markdown` 或等价 Markdown renderer。

### 11.3 Agent

- LangGraph agent。
- LangChain ChatOpenAI 或等价 OpenAI-compatible client。
- tools 调用当前业务服务代码。
- 使用 CopilotKit middleware 与 state streaming。
- `langgraph-cli dev --port 8123` 本地运行。

### 11.4 Backend Service Layer

短期：

- 保留 FastAPI REST，保证已有功能和测试不丢。
- LangGraph tools 可以直接 import `backend/services/*`。

中期：

- 把无框架依赖的业务函数沉淀为共享 service package。
- FastAPI 只保留下载、调试或兼容用途。

### 11.5 Desktop

- Electron 主进程。
- 默认加载 `http://localhost:3000`。
- 启动时检测并拉起：
  - Next.js UI。
  - LangGraph agent。
  - 迁移期 FastAPI 服务，如仍需要文件/下载 REST。
- Electron 当前仅用于本地开发桌面壳，不负责正式安装包。

## 12. 本地开发脚本

参考 Starter 保持脚本命名：

| Script | 作用 |
| --- | --- |
| `npm run dev` | 同时启动 UI、agent、Electron，迁移期可同时启动 REST backend |
| `npm run dev:ui` | 启动 Next.js |
| `npm run dev:agent` | 启动 LangGraph agent |
| `npm run dev:electron` | 启动 Electron |
| `npm run install:agent` | 安装 agent Python 依赖 |
| `npm run typecheck` | 前端和 Electron 类型检查 |
| `npm run test:backend` | 当前业务服务测试 |
| `npm run test:agent` | 后续 LangGraph tools 测试 |

## 13. 迁移计划

### Phase 0：PRD 与目标对齐

- 更新 PRD。
- 明确使用 Generative UI Starter Project 作为主参考。
- 不新增业务代码。

### Phase 1：引入 Starter 框架层

- 引入 CopilotKit 前端依赖。
- 引入 `/api/copilotkit` route。
- 引入 `agent/` LangGraph skeleton。
- 复用 Starter 的脚本方式。
- 保留当前页面和 REST 功能作为 fallback。

### Phase 2：迁移 Chat 与工具执行

- 将阶段一提取、确认修正、阶段二生成封装为 LangGraph tools。
- Chat 调用 tools。
- 前端展示工具执行状态。
- 工作台状态来自 agent state，而不是手写轮询 REST。

### Phase 3：工作台重构

- 使用 Starter `ExampleLayout` 思路改造为标书工作台。
- 保留当前 API 配置、上传、成果预览 UI 中能复用的部分。
- 删除 todo/flight/dashboard 演示元素。

### Phase 4：成果渲染增强

- 可选引入 A2UI。
- 结构化展示：
  - 信息提取卡片。
  - 评分标准响应矩阵。
  - 图纸需求清单。
  - 成果下载面板。

### Phase 5：清理过渡层

- 评估是否保留 FastAPI REST。
- 合并重复状态管理。
- 完善 README、测试和启动脚本。

## 14. 验收标准

### 14.1 功能验收

- 桌面应用可启动。
- CopilotKit Chat 可连接本地 LangGraph agent。
- 能上传 TXT、MD、DOCX、PDF 并解析文本。
- 空文件、损坏文件、扫描 PDF 有明确错误。
- DeepSeek 预设会自动填入 `https://api.deepseek.com` 和 `deepseek-v4-pro`。
- 阶段一未完成时不能确认和生成。
- 阶段一确认后才能进入模板选择。
- 生成完成后工作台可预览四类成果。
- 单文件下载和 ZIP 下载可用。

### 14.2 技术验收

迁移期必须继续通过：

```bash
npm run test:backend
npm run typecheck
npm --prefix frontend run build
```

引入 LangGraph agent 后新增：

```bash
npm run install:agent
npm run dev:agent
```

后续补充：

```bash
npm run test:agent
```

### 14.3 Starter 对齐验收

- 存在 CopilotKit runtime route。
- 存在 LangGraph `agent/main.py`。
- `npm run dev` 可同时拉起 UI、agent 和 Electron。
- 前端 Chat 使用 CopilotKit，而不是完全自研消息列表。
- Agent tools 复用当前业务服务代码。
- 不引入 Starter 的无关演示业务。

## 15. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| CopilotKit/LangGraph 引入后复杂度增加 | 迁移成本上升 | 分阶段迁移，保留 REST fallback |
| 文件上传与 LangGraph state 衔接复杂 | 文件内容无法进入 agent | 先保留上传 REST 或 Next route，再把文本写入 agent state |
| 大型招标文件超过模型上下文 | 阶段一遗漏信息 | V1 截断并提示；后续加分块提取 |
| 扫描 PDF 无文本层 | 无法提取 | 明确提示先 OCR |
| 国产兼容接口不支持 `developer` role | LLM 请求失败 | 强制使用 `system` role |
| Electron 同时拉起多个服务更复杂 | 启动失败概率提高 | 分别提供 `dev:ui`、`dev:agent`、`dev:electron` 调试入口 |
| 状态双写 | 前端 state、REST store、LangGraph state 不一致 | Phase 2 后以 LangGraph state 为准 |

## 16. 后续迭代

- A2UI 结构化渲染评分矩阵和成果卡片。
- 项目历史：SQLite 保存项目、消息、阶段一结果和成果。
- DOCX 导出：把 Markdown 成果转换为 Word。
- OCR：集成本地或云 OCR 处理扫描 PDF。
- 分块提取：大型招标文件按章节分块，最后合并评分标准。
- token 或章节级流式输出。
- 正式桌面打包：Electron Builder、签名、公证、安装包。
- 企业知识库：沉淀历史评分标准、提示词和方案内容。
