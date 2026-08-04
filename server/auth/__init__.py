"""
认证子包（飞书 SSO）。

模块划分：
- signing.py       签名凭证的签发与校验（HMAC-SHA256，标准库实现）
- session_store.py 会话、OAuth state、跨域跳转凭证的持久化
- feishu.py        飞书开放平台客户端（任务 4）
- identity.py      身份解析中间件（任务 6）
- emergency.py     应急管理员通道（任务 12）

本包不引入任何第三方依赖，项目运行依赖保持 flask + bcrypt 两项。
"""
