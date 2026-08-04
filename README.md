# WebApps Link Manager

企业内网 HTML 文件分享与管理系统 — 轻量级的内网"应用商店"。

## 功能特性

- 📁 **文件管理** — 扫描展示、复制链接、编辑信息、删除文件
- 📦 **ZIP 上传** — 一键解压，自动识别 index.html 入口
- 🔐 **密码保护** — 文件访问密码 + 永久访问令牌
- 👥 **管理员系统** — 超级管理员/普通管理员权限分离
- 📋 **日志审计** — 完整的管理员操作和文件操作记录
- 🏷️ **产品线管理** — 13 个产品线分类，颜色标签区分
- 🌗 **主题切换** — 深色/浅色/自动模式

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Vite + Ant Design 5 |
| 后端 | Python Flask |
| 数据存储 | JSON 文件 |

## 项目结构

```
webapps/
├── frontend/           # React 前端源码
│   ├── src/
│   │   ├── App.tsx     # 主组件
│   │   ├── api.ts      # API 调用封装
│   │   ├── types.ts    # TypeScript 类型
│   │   └── components/ # UI 组件
│   └── package.json
├── server/             # Flask 后端
│   ├── app.py          # 主程序 + API 路由
│   ├── file_manager.py # 文件操作
│   ├── metadata.py     # 元数据管理
│   └── config.py       # 配置文件
├── PRD.md              # 产品需求文档
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install flask
cd frontend && npm install
```

### 2. 构建前端（如有修改）

```bash
cd frontend && npm run build
```

### 3. 启动服务

```bash
cd server && python3 app.py
```

### 4. 访问

- 管理界面：http://localhost:8080/
- 文件访问：http://localhost:8080/files/文件名

## 初始配置

首次访问时创建超级管理员账户。

## License

MIT

## 飞书扫码登录（SSO）

系统身份来自飞书扫码登录，项目所有权绑定飞书账号（不再依赖来源 IP）。

### 首次配置

```bash
cp .env.example .env
# 编辑 .env，填入下面两项（在飞书开放平台「凭证与基础信息」获取）
#   FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
#   FEISHU_APP_SECRET=<你的 App Secret>

python3 server/migrate_identity.py     # 补齐所有权字段，幂等可重复执行
cd server && python3 app.py
```

`.env` 已在 `.gitignore` 排除范围内。**注意不要把 Secret 填进 `.env.example`** ——
那个文件是会进版本库的模板，两者只差 `.example` 后缀，很容易看错。

### 飞书开放平台需要配置什么

1. 创建**企业自建应用**，拿 App ID 与 App Secret
2. 「安全设置」里添加重定向 URL：`http://localhost:8080/auth/feishu/callback`
   （生产环境另加 `https://app.<域名>/auth/feishu/callback`）
3. 「权限管理」申请三项：获取用户基本信息、校验用户是否为应用管理员、获取应用管理员 ID
   —— **不需要**通讯录读取权限
4. 「测试企业和人员」把自己加进去，未发布状态下即可自测
5. 让同事也能登录需要：管理员审批权限 → 发布版本 → 设置可用范围

### 首个超级管理员

管理员名单为空时，首个通过飞书应用管理员校验的登录者自动成为超级管理员。
之后完全依据系统内部名单判定，不再依赖飞书接口可用性。

### 存量项目的归属

改造前的项目 `uploader_ip` 反查不到人（DHCP 会变），所以迁移后它们处于
「未指定负责人」状态，**普通员工不能编辑**。超管登录后在导航栏「指定负责人」
里批量补上即可。候选人只能是登录过本系统的同事。

### 飞书不可用时怎么进系统

应急管理员通道只绑回环地址：

```bash
ssh -L 8099:127.0.0.1:8099 user@server
# 本地浏览器打开 http://127.0.0.1:8099/emergency/login
```

账号沿用 `metadata.json` 里既有的用户名密码条目，登录后有 60 分钟超管权限。

### 测试

```bash
pip3 install -r requirements-dev.txt
python3 -m pytest server/tests -q                    # 单元测试 + 属性测试
python3 server/tests/security_regression.py          # 安全回归（需服务已启动）
```

更多部署细节见 `deploy/README.md`。
