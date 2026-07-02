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
