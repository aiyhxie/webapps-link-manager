# 部署说明（飞书 SSO 版）

## 两种运行形态

| | 形态 A · 单进程 | 形态 B · 网关 |
|---|---|---|
| 适用 | 本机开发、内网试运行 | 公网生产 |
| 拓扑 | 一个 Flask 进程监听 8080 | Nginx 唯一入口 + Flask 后端 |
| 身份来源 | 会话 Cookie | Nginx 注入的 `X-Auth-*` 头 |
| 域名 | 无 | 管理域 + 预览域 |
| `AUTH_MODE` | `embedded` | `gateway` |

形态 A 下 `X-Auth-*` 头在 WSGI 层被直接删除，应用根本看不到；形态 B 下只有对端在
`TRUSTED_GATEWAY_IPS` 内才采信这些头。两条机制互不依赖，任一生效即可挡住伪造。

## 形态 A：本机开发

```bash
cp .env.example .env
# 编辑 .env，填 FEISHU_APP_ID 与 FEISHU_APP_SECRET
python3 server/migrate_identity.py      # 首次运行需要，幂等可重复执行
cd server && python3 app.py
```

飞书开放平台的重定向 URL 需要包含你实际访问的地址，例如
`http://localhost:8080/auth/feishu/callback`。**注意本机 IP 会随所连 WiFi 变化**，
换网络后要么用 `localhost` 访问，要么在飞书后台补上新 IP 的回调地址。

首个通过飞书应用管理员校验的登录者会自动成为超级管理员。

## 形态 B：公网生产

前置条件：Linux 服务器、已备案域名、两个子域的 DNS 解析、Let's Encrypt 证书。

1. **应用侧配置**

   ```bash
   AUTH_MODE=gateway
   DEPLOY_ENV=production
   ADMIN_ORIGIN=https://app.<域名>
   PREVIEW_ORIGIN=https://preview.<域名>
   TRUSTED_GATEWAY_IPS=127.0.0.1,::1
   AUTH_SIGNING_SECRET=<python3 -c "import secrets;print(secrets.token_urlsafe(32))">
   ```

   `AUTH_SIGNING_SECRET` 在 gateway 模式下必须显式设置，缺失会拒绝启动。

2. **飞书开放平台**：重定向 URL 增加 `https://app.<域名>/auth/feishu/callback`。
   生产环境的允许回调列表**排除** http 开发地址，防止有人拿内网地址绕过 HTTPS。

3. **Nginx**：以 `nginx.conf.example` 为基础，替换域名与证书路径。

4. **数据迁移**：把 `webapps/`、`versions/`、`metadata.json`、`logs/` 从旧机器搬过来，
   然后运行 `python3 server/migrate_identity.py`。

5. **验证**：`python3 server/tests/security_regression.py --base https://app.<域名>`

## 换用 gunicorn 时必须处理的两件事

**应急通道会在每个 worker 里各起一份**并争抢 8099 端口。当前实现对端口占用做了
容错（打日志不崩），但正确做法是二选一：

- 只在主 worker 启动：用 gunicorn 的 `--preload` 配合进程判断
- 独立进程运行：`EMERGENCY_ENABLED=false` 关掉内置的，另起一个只跑应急通道的进程

**会话存储的并发是安全的**：它用的是 `fcntl.flock` 跨进程文件锁，不是线程锁，
多 worker 下依然正确。但要注意每次会话变更都会全量重写 JSON 文件，
用户数到数百人时应改用 SQLite。

推荐起法：

```bash
gunicorn --workers 4 --bind 127.0.0.1:8080 --chdir server "app:create_app()"
```

注意 `create_app()` 不会执行认证配置校验（那是 `main()` 做的），
所以用 gunicorn 时要在启动脚本里先跑一次：

```bash
python3 -c "import sys;sys.path.insert(0,'server');import config;config.abort_on_invalid_auth_config()"
```

## 应急管理员通道怎么用

它只绑 `127.0.0.1:8099`，Nginx 不代理，配置成对外可达会导致应用**拒绝启动**。

```bash
ssh -L 8099:127.0.0.1:8099 user@server
# 然后本地浏览器打开 http://127.0.0.1:8099/emergency/login
```

账号沿用 `metadata.json` 里既有的 `_system_admins_` 条目（bcrypt 存储）。
登录后获得 60 分钟超级管理员权限，不会因活动而延长。每次登录尝试都会写审计日志。

## 运行时文件

以下文件由程序生成，都已在 `.gitignore` 中排除，迁移时按需处理：

| 文件 | 说明 | 迁移时 |
|---|---|---|
| `.env` | 凭据配置 | 手工重建，不要拷贝 |
| `.auth_secret` | 签名密钥（embedded 模式自动生成） | 生产用环境变量，不需要 |
| `auth_sessions.json` | 会话、OAuth state、跳转凭证 | 不用搬，让大家重新登录 |
| `metadata.json` | 项目元数据 + 用户档案 + 管理员名单 | **必须搬** |
| `webapps/` `versions/` | 项目文件与历史版本归档 | **必须搬** |
| `logs/audit.jsonl` | 审计日志 | 建议搬 |
