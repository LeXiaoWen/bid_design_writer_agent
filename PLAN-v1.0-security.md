# 本机单用户管理与安全设计 v1.0

## 1. 设计目标

为 Electron + FastAPI + SQLite 本地桌面应用提供本机单用户账号体系和安全防护，满足以下目标：

1. 防止未授权人员打开应用直接查看项目数据和招标文件内容。
2. 防止本机其他网页或进程在不知道密钥的情况下调用本地 API。
3. 保护模型 API key 不落库明文。
4. 不采集姓名、单位、角色、邮箱等个人资料。

---

## 2. 账号模型

### 2.1 单用户模型

- 整个应用只有一个本机账号，所有数据归属该账号。
- 首次启动时创建账号，后续启动需登录。
- 不提供注册多个账号或账号切换功能。
- 账号仅包含用户名和密码两个字段。

### 2.2 用户表结构

```sql
CREATE TABLE users (
    id              TEXT PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_login_at   TEXT
);
```

不包含姓名、单位、角色、邮箱、手机号等字段。

---

## 3. 密码安全

### 3.1 密码哈希

- 使用 `argon2-cffi` 库的 Argon2id 变体。
- 通过 `PasswordHasher` 默认参数进行哈希（time_cost=3, memory_cost=65536, parallelism=4）。
- 登录时若检测到哈希参数需要更新，自动 rehash。
- 数据库中仅存储哈希值，不存储明文。

### 3.2 密码规则

- 无强制复杂度要求（本地桌面应用，物理访问即最高权限）。
- 前端校验：用户名和密码不能为空，注册时两次密码必须一致。

### 3.3 修改密码

- 需验证当前密码。
- 修改后所有旧 session 失效，需重新登录。

---

## 4. 会话管理

### 4.1 Session 创建

```text
用户登录 → 验证密码 → secrets.token_urlsafe(32) 生成 token
  → SHA-256(token) 存入 auth_sessions 表
  → 原始 token 返回前端
```

### 4.2 Session 存储

```sql
CREATE TABLE auth_sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    token_hash  TEXT UNIQUE NOT NULL,
    expires_at  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
```

- token 原文只有前端持有，后端仅存储 SHA-256 哈希。
- 默认 8 小时过期。
- 支持多条 session 共存（多窗口场景）。

### 4.3 Session 校验

```text
请求 → 提取 Authorization: Bearer <token>
  → SHA-256(token) → 查 auth_sessions WHERE token_hash = ? AND expires_at > utc_now()
  → 命中 → 注入 request.state.user
  → 未命中 → 401
```

### 4.4 Session 销毁

- 主动登出：删除对应的 `auth_sessions` 行。
- 修改密码：该用户的所有 session 一并删除。
- 过期自动失效（数据库查询时检查 `expires_at`）。

### 4.5 前端存储

- Token 存储在 `sessionStorage`，关闭标签页即失效。
- 不使用 `localStorage` 或 Cookie。
- 退出登录或收到 401 后清空 token 和全部业务状态。

---

## 5. 本机 API 访问控制

### 5.1 双重校验

```
请求 /api/v1/*（公开端点除外）
  │
  ├── 校验 1：X-App-Auth-Secret
  │   ├── 生成：Electron 主进程启动时 randomBytes(32).toString("base64url")
  │   ├── 注入：通过环境变量 APP_AUTH_SECRET 传入后端
  │   ├── 传递：前端 preload IPC → window.authGetAppSecret() → 附加到请求头
  │   ├── 开发模式：APP_AUTH_SECRET 为空时跳过此校验
  │   └── 失败 → 403
  │
  └── 校验 2：Bearer Token
      ├── 公开端点白名单：
      │     /api/v1/auth/status
      │     /api/v1/auth/setup
      │     /api/v1/auth/login
      └── 失败 → 401
```

### 5.2 为什么需要 APP_AUTH_SECRET

Electron 应用加载的是 `localhost:3000` 或 `app://frontend`，后端绑定在 `127.0.0.1:8765`。如果用户浏览器中打开了恶意网页，该网页可以通过 `fetch("http://127.0.0.1:8765/api/v1/...")` 调用本地 API。`APP_AUTH_SECRET` 是一个只有 Electron 进程知道的随机密钥，恶意网页无法获取，因此无法通过第一层校验。

### 5.3 中间件实现

```python
@app.middleware("http")
async def require_local_auth(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)
    if not path.startswith("/api/v1/") or path in PUBLIC_API_V1_PATHS:
        return await call_next(request)

    if not app_auth_secret_is_valid(request):
        return JSONResponse(status_code=403, content={"detail": "本机访问密钥无效。"})

    user = user_from_token(bearer_token(request))
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "请先登录。"})
    request.state.user = user
    return await call_next(request)
```

---

## 6. API Key 保护

### 6.1 存储策略

```
系统钥匙串（macOS Keychain / Windows Credential Manager）
  ↑ keyring 库
  │
KeyringBridge（backend/services/workbench_store.py）
  ├── service name: "ai-workbench-desktop"
  ├── key: credential_key（随机 UUID，存在 SQLite）
  └── value: API key 明文
        │
SQLite provider_profiles 表
  ├── credential_key: "a1b2c3d4-..."（keyring key）
  └── has_key: 实时从 keyring 检查，响应中回显
```

### 6.2 三级降级策略

| 条件 | 行为 |
| --- | --- |
| keyring 可用 | 写入 macOS Keychain / Windows Credential Manager |
| keyring 不可用 + `AI_WORKBENCH_ALLOW_MEMORY_CREDENTIALS=true` | 回退到进程内存字典（仅开发/测试） |
| keyring 不可用 + 生产模式 | 抛出 RuntimeError |

### 6.3 响应安全

- Provider Profile 列表和详情响应中**永不回显** API key 内容。
- `has_key` 字段由实时 keyring 查询得出，反映真实存储状态。
- 前端 API key 输入框 `type="password"`，placeholder 提示「保存到系统钥匙串」。

---

## 7. 认证 API

所有认证接口前缀 `/api/v1/auth/`，免 Bearer Token 校验。

### 7.1 GET /api/v1/auth/status

无需登录即可调用。返回：

```json
{
  "setup_required": true,
  "authenticated": false,
  "username": null
}
```

- `setup_required`：数据库中无用户记录时为 `true`。
- `authenticated`：当前请求携带有效 session 时为 `true`。
- `username`：已认证时返回当前用户名。

前端根据 `setup_required` 决定显示注册页还是登录页。

### 7.2 POST /api/v1/auth/setup

仅在无用户时可用。Body：

```json
{
  "username": "admin",
  "password": "mypassword"
}
```

成功后返回：

```json
{
  "token": "abc123...",
  "expires_at": "2026-07-07T04:00:00+00:00",
  "username": "admin"
}
```

### 7.3 POST /api/v1/auth/login

Body 同上。返回格式同上。

### 7.4 POST /api/v1/auth/logout

需携带有效 Bearer Token。撤销当前 session。

### 7.5 GET /api/v1/me

需登录。返回：

```json
{
  "id": "uuid",
  "username": "admin",
  "created_at": "2026-07-06T12:00:00+00:00",
  "updated_at": "2026-07-06T12:00:00+00:00",
  "last_login_at": "2026-07-06T20:00:00+00:00"
}
```

### 7.6 POST /api/v1/auth/change-password

需登录。Body：

```json
{
  "current_password": "old",
  "new_password": "new"
}
```

成功后所有旧 session 失效，需重新登录。

---

## 8. 行为摘要隐私

### 8.1 触发条件

阶段二生成成功后，后台任务自动调用 `save_behavior_report()`。

### 8.2 摘要内容

- 文件：`用户行为与需求摘要.md`，保存到本机应用数据目录。
- 内容：用户目标、补充/修正点、格式偏好、阶段卡点、不满意点、skill 优化建议、关键短片段和成果文件名。
- **不包含**：原始招标文件、上传原文件、完整聊天记录、API key、密码。

### 8.3 隐私控制

- 行为摘要仅保存在本机，不发送邮件。
- 保存失败不影响成果下载。
- API key、token、邮箱、手机号等敏感片段必须脱敏。

---

## 9. 前端认证流程

### 9.1 状态机

```text
App 启动
  │
  ▼
loading ── GET /api/v1/auth/status ──▶ setup_required=true  → setup
  │                                     setup_required=false
  │                                     authenticated=false   → login
  │                                     authenticated=true    → ready
  ▼
ready（工作台）
  │
  ├── 退出登录 → 调用 logout API → 清空 sessionStorage → login
  ├── 修改密码 → 调用 change-password API → 清空 sessionStorage → login
  └── 收到 401 → 清空 sessionStorage → login
```

### 9.2 AuthMode 枚举

```typescript
type AuthMode = "loading" | "setup" | "login" | "ready";
```

### 9.3 业务数据加载时机

仅在 `authMode === "ready"` 时加载项目、对话、消息、模型配置、搜索和成果下载。登录前 UI 仅渲染认证表单。

---

## 10. 安全边界

### 10.1 防护目标

| 威胁 | 防护措施 |
| --- | --- |
| 未登录用户打开应用 | 启动即显示登录页，所有 API 需 Bearer Token |
| 恶意网页调用本地 API | APP_AUTH_SECRET 仅 Electron 进程知道 |
| API key 从数据库中泄露 | keyring 存系统钥匙串，数据库不存明文 |
| Session 被窃取（本机） | 8 小时过期，SHA-256 哈希存储 |
| 密码泄露 | Argon2id 哈希，不存明文 |

### 10.2 不防护

| 威胁 | 原因 |
| --- | --- |
| 本机管理员直接读取 SQLite 文件 | 物理访问无法通过软件防御 |
| 屏幕录制、键盘记录 | 系统级安全范畴 |
| 用户主动导出的文件外泄 | 用户自主行为 |
| 内存中的 API key 被 dump | 需要系统级权限 |

### 10.3 V1 范围外

- 全库加密。
- 团队多用户、角色权限分级（RBAC）。
- 云端同步、企业 SSO。
- 双因素认证（2FA）。
- 忘记密码自助恢复（需手动操作 SQLite）。
- 首次注册隐私说明页。
