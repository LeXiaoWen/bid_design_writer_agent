# 本机单用户管理与安全加固方案（精简账号版）

## Summary

为当前 Electron + FastAPI + SQLite 本地应用增加本机单用户账号体系。v1 只保留用户名和密码，不采集姓名、单位、角色、邮箱等个人资料。目标是防止他人直接打开应用、减少本机网页或其他进程误调用 API、保护模型 API key 不落库明文；不承诺防本机管理员或恶意进程直接读取数据库文件。

## Key Changes

- 用户与登录：
  - 首次启动显示创建本机账号页：用户名、密码、确认密码。
  - 后续启动显示登录页：用户名、密码。
  - SQLite 新增单用户 `users` 表：`id`、`username`、`password_hash`、`created_at`、`updated_at`、`last_login_at`。
  - 历史项目、对话、workflow、模型配置默认归属该唯一用户。
  - 密码使用 `argon2-cffi` 的 Argon2id 哈希，不保存明文。
- 本地 API 访问控制：
  - 新增认证接口：`GET /api/v1/auth/status`、`POST /api/v1/auth/setup`、`POST /api/v1/auth/login`、`POST /api/v1/auth/logout`、`GET /api/v1/me`、`POST /api/v1/auth/change-password`。
  - 除 `/health` 和认证入口外，所有 `/api/v1/*` 必须校验登录 session。
  - Electron 启动后端时生成随机 `APP_AUTH_SECRET`；后端要求业务请求携带该本机密钥，前端通过 preload 获取并自动带上。
  - 登录 session token 使用安全随机值，默认 8 小时过期；退出登录立即失效。
- API key 与敏感信息：
  - 模型 API key 使用 Python `keyring` 保存到系统钥匙串，SQLite 只保存 `credential_key`。
  - keyring 不可用时，生产模式返回明确错误；开发/测试模式可使用内存凭据桥。
  - provider profile 响应继续只返回 `has_key`，不回显 API key。
- 前端体验：
  - 移除当前 `localStorage` 伪登录，改为真实登录、退出登录、修改密码。
  - 左下角只显示用户名和登录状态，不再展示姓名、单位、角色、邮箱。
  - 登录前不加载项目、对话、workflow、搜索、模型配置或成果下载。
  - token 存 `sessionStorage`；退出登录或 401 后清空并回登录页。
  - 首次创建账号时展示隐私说明：本机数据库未全库加密；阶段二完成后会按当前配置后台发送行为摘要与成果包，可通过配置关闭或修改收件人。
- 文档与恢复：
  - README 增加安全边界、keyring 依赖、行为摘要隐私说明、忘记密码处理方式。
  - 忘记密码 v1 提供本机恢复脚本，仅清除账号和 session，不删除项目数据；文档明确该脚本等同本机文件访问权限，不能作为强安全边界。

## Security Boundaries

- 防护目标：
  - 防止普通人员打开应用直接查看数据。
  - 防止普通网页在不知道 `APP_AUTH_SECRET` 的情况下直接调用本地 API。
  - 防止模型 API key 明文落入 SQLite。
  - 防止接口未登录访问项目、对话、招标文本、生成成果和模型配置。
- 不防护：
  - 本机管理员、恶意进程或有文件访问权限的人直接读取 SQLite。
  - 屏幕录制、键盘记录、系统级恶意软件。
  - 用户主动导出的 Markdown/ZIP 文件外泄。
- 明确默认：
  - v1 不做全库加密。
  - v1 不做团队多用户、权限分级、云端同步、企业 SSO。
  - v1 不采集姓名、单位、角色、邮箱。

## Test Plan

- 后端：
  - 无用户时 `auth/status` 返回需要 setup；setup 后历史数据归属唯一用户。
  - `users` 表不包含姓名、单位、角色、邮箱字段。
  - 密码哈希不是明文；正确登录成功，错误登录失败。
  - 未登录、缺 session、缺 `APP_AUTH_SECRET`、过期 session 访问业务接口均返回 401/403。
  - logout 后 session 失效；修改密码后旧 session 失效。
  - provider profile 不回显 API key；keyring 保存/读取成功；keyring 不可用时生产模式返回可读错误。
  - 行为摘要继续脱敏 API key/token/password。
- 前端：
  - 首次启动进入创建账号页；已创建账号后进入登录页。
  - 登录后加载工作台；退出登录后清空界面并回登录页。
  - 左下角只展示用户名/登录状态。
  - 401 自动回登录页。
  - 修改密码流程可用。
  - 登录前无法通过 UI 触发项目、对话、搜索、workflow、下载。
- 打包与集成：
  - `npm run typecheck`
  - `npm run test:backend`
  - `npm run test:frontend`
  - `npm run build`
  - packaged Electron 中 `APP_AUTH_SECRET` 注入、preload 获取、keyring 访问均可用。

## Assumptions

- v1 按"本机单用户 + 账号密码"实现。
- 账号只包含用户名和密码。
- 历史数据自动归属唯一用户，不做数据选择或拆分。
- API key 默认使用系统钥匙串；开发和测试环境才允许内存凭据桥。
- 行为摘要邮件功能保留，但首次 setup 必须展示隐私说明，并允许通过环境变量禁用。
