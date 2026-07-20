# 主题系统增强开发文档

> 基于 Codex-Dream-Skin 项目分析，将可复用的算法和设计模式移植到 bid 项目，
> 在现有架构上增强，不重写、不替换现有主题系统。

## 一、背景

Codex-Dream-Skin (https://github.com/Fei-Away/Codex-Dream-Skin) 是给 OpenAI Codex 桌面端做 CDP 注入换肤的工具。
该项目约 80% 的代码（CDP 注入框架、桌面安装脚本、plist 文件管理）与 bid 项目的 Web 应用架构不兼容，
但其**图片分析算法**和**CSS 遮罩设计模式**值得移植。

bid 项目已有独立的主题系统（图片上传、校验、存储、CSS 变量、自适应调色板、前端 ThemePanel），
本次增强在此基础上做增量改进，不动架构。

## 二、增强目标

| 增强项 | 当前状态 | 目标状态 |
|--------|---------|---------|
| 图片调色板分析 | 仅取平均 RGB 色 | HSL 直方图 + 显著性检测 → 更准确的强调色 |
| 安全区域检测 | 仅左右信息密度比较 | 加入宽高比分类 + 边缘检测 → 更智能的安全区 |
| 图片焦点定位 | 无 | saliency map → 自动确定视觉焦点 |
| 宽高比分类 | 无 | ultrawide/wide/landscape/square/portrait |
| CSS 遮罩系统 | 单一固定渐变 | 按 safeArea 动态四向渐变 |
| 分析结果缓存 | 无 | LRU 缓存避免重复分析 |
| 明暗检测 | 简单判断 | 多层次检测链路 |

## 三、实施阶段

### 阶段 1：增强 `themeAnalysis.ts` 图片分析算法（优先级 P0）

**涉及文件：**
- `frontend/src/lib/themeAnalysis.ts` — 重写分析函数，新增算法模块
- `frontend/src/lib/types.ts` — 可能新增类型

**移植的算法逻辑：**

1. **HSL 色相直方图（24-bin）**
   - 对缩略图像素按色相分桶（每 15° 一个桶）
   - 用饱和度 × 亮度距离中心偏移作为权重
   - 选权重最高的桶 → 主导色相 → 强调色

2. **显著性检测（saliency map）**
   - 计算亮度偏差 + 饱和度 + 边缘梯度的加权和
   - 按像素位置加权得到视觉焦点 (focusX, focusY)

3. **安全区域检测增强**
   - 左/右区域信息密度比较（已有）
   - 加入边缘梯度作为信息量指标

4. **宽高比分类**
   - ratio ≥ 2.25 → "ultrawide"
   - ratio ≥ 1.45 → "wide"
   - ratio ≥ 1.08 → "landscape"
   - ratio ≥ 0.9 → "square"
   - else → "portrait"

5. **分析缓存**
   - 基于图片 blob URL 的 LRU 缓存
   - 最大缓存 8 个结果

**输出增强：**
- `ThemePresentation` 类型扩展：新增 `safeArea`（已有）、`aspect`、`taskMode`、`wide`

### 阶段 2：增强 `globals.css` 遮罩系统（优先级 P0）

**涉及文件：**
- `frontend/src/app/globals.css` — CSS 变量扩展
- `frontend/src/lib/themeAnalysis.ts` — 输出 `aspect`、`wide` 等属性

**CSS 增强：**

1. **四向遮罩切换**
   - `data-theme-safe="left"` → 渐变从左侧（图片焦点在右）
   - `data-theme-safe="right"` → 渐变从右侧（图片焦点在左）
   - `data-theme-safe="center"` → 双向渐变
   - `data-theme-safe="none"` → 全画面均匀覆盖

2. **宽屏图片处理**
   - `data-theme-aspect="wide|ultrawide"` → 背景覆盖整个窗口
   - 非宽屏 → 仅 hero 区域展示

3. **工作区背景模式**
   - `data-theme-task="ambient"` → 工作区半透明覆盖（已有类似逻辑）
   - `data-theme-task="banner"` → 顶部横幅展示

### 阶段 3：增强明暗模式检测（优先级 P1，可选）

**涉及文件：**
- `frontend/src/hooks/useTheme.ts` — 增强 auto 模式判定

**检测链路：**
1. 用户显式设置 appearance（优先级最高）
2. data-theme / data-color-mode 属性
3. prefers-color-scheme 媒体查询
4. 背景亮度分析（仅在无背景时使用）

## 四、不涉及的范围

- 不新增后端 API
- 不修改数据库 schema
- 不新增前端路由
- 不修改 `ThemePanel.tsx` 组件 UI
- 不引入新依赖包

## 五、验收标准

1. 上传非纯色图片后，强调色与图片主色调一致
2. 图片焦点在左侧时，侧边栏遮罩从右侧渐变（反之亦然）
3. 超宽图片作为全窗背景展示
4. 切换主题后分析结果被缓存，二次切换不重新分析
5. 现有功能不受影响：系统主题、上传、删除、切换
