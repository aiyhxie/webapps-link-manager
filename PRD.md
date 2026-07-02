# WebApps Link Manager 产品需求文档 (PRD)

## 1. 产品概述

### 1.1 产品定位
WebApps Link Manager 是一款面向企业内网的 HTML 文件分享与管理系统，类似于一个轻量级的内网"应用商店"，支持上传、分享、管理 HTML 应用和原型。

### 1.2 核心价值
- 无需复杂部署，快速分享 HTML 原型和工具
- 支持 ZIP 包一键解压，自动识别项目结构
- 基于 IP 的文件所有权机制，保障安全
- 完整的管理员体系和操作日志审计

### 1.3 目标用户
- 产品经理（上传和分享原型）
- 开发人员（分享内部工具）
- 管理员（管理文件和用户）

---

## 2. 功能清单

### 2.1 管理员系统

| 功能 | 说明 |
|------|------|
| 超级管理员 | 第一个创建的管理员为超级管理员，拥有所有权限 |
| 管理员登录 | 用户名+密码登录，支持会话保持 |
| 管理员管理 | 超级管理员可添加、删除普通管理员 |
| 修改密码 | 管理员可修改自己的密码 |
| 查看日志 | 管理员可查看系统操作日志 |

**权限说明：**
- 普通管理员：对自己上传的文件拥有编辑、删除权限
- 超级管理员：对所有文件拥有编辑、删除权限，可管理其他管理员

### 2.2 文件管理

| 功能 | 说明 |
|------|------|
| 扫描展示 | 自动扫描 webapps 目录下所有 HTML 文件 |
| 根目录文件 | 根目录的 .html 文件单独展示 |
| 子目录文件 | 一级子目录中的 index.html 作为项目入口 |
| 复制链接 | 一键复制文件访问链接 |
| 编辑信息 | 可编辑标题、描述、产品线 |
| 删除文件 | 仅文件上传者或超级管理员可删除 |
| 访问统计 | 记录文件访问次数（日志） |

### 2.3 文件上传

| 功能 | 说明 |
|------|------|
| HTML 上传 | 直接上传 HTML 文件到根目录 |
| ZIP 上传 | 上传 ZIP 压缩包，自动解压 |
| 拖拽上传 | 支持拖拽文件到上传区域 |
| 编码兼容 | 支持 UTF-8、GBK、CP437 编码的 ZIP |
| 自动识别 | ZIP 包中查找 index.html 作为入口 |
| 嵌套结构 | 支持 index.html 在根目录或子目录 |

### 2.4 密码保护

| 功能 | 说明 |
|------|------|
| 设置密码 | 可为任意文件设置访问密码 |
| 密码验证 | 访问时需输入正确密码 |
| 访问令牌 | 密码验证后生成永久访问令牌 |
| 令牌复用 | 同一令牌可多次访问 |

### 2.5 日志系统

| 功能 | 说明 |
|------|------|
| 管理员操作 | 记录管理员登录、退出、添加/删除用户、修改密码 |
| 文件操作 | 记录上传、编辑、删除、访问文件 |
| 登录失败 | 记录登录失败的用户名和 IP |
| 日志查看 | 管理员可查看和筛选日志 |

**日志格式：**
```
时间 | 级别 | 操作类型 | 详情
2026-06-26 17:00:00 | INFO | ADMIN [用户名] 登录: 超级管理员
2026-06-26 17:05:00 | INFO | FILE 上传ZIP: 文件名 -> keys
2026-06-26 17:10:00 | WARNING | LOGIN FAILED | 用户名: xxx | IP: xxx
```

### 2.6 产品线管理

| 功能 | 说明 |
|------|------|
| 自动识别 | 根据文件路径或内容关键词自动识别产品线 |
| 手动设置 | 可手动指定产品线分类 |
| 筛选展示 | 按产品线筛选文件列表 |
| 排序功能 | 支持按标题、上传时间排序 |

**内置产品线：**
- 康老板AI医生、康老板健康、康老板商城
- 康店代理商、康管家、旅途管家
- 老板云、老板帮、幸福绩效
- 飞联天下、创业天使、会议系统
- 加速中心、数智化、自搭云、企座

### 2.7 主题系统

| 功能 | 说明 |
|------|------|
| 深色模式 | 适配深色主题 |
| 浅色模式 | 适配浅色主题 |
| 自动模式 | 跟随系统主题自动切换 |

---

## 3. 技术架构

### 3.1 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python Flask |
| 前端 | React + TypeScript + Vite |
| UI 组件 | Ant Design |
| 数据存储 | JSON 文件 (metadata.json) |
| 日志存储 | 文本文件 (logs/webapps.log) |

### 3.2 目录结构

```
~/webapps/
├── server/                    # Flask 后端
│   ├── app.py                 # 主程序 + API 路由
│   ├── file_manager.py        # 文件操作逻辑
│   ├── metadata.py             # 元数据管理
│   ├── config.py               # 配置文件
│   └── templates/             # 前端静态文件
│       └── index.html
├── frontend/                  # React 前端源码
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts
│   │   └── components/
│   └── dist/                  # 构建产物
├── webapps/                   # 用户 HTML 文件存放
│   ├── index.html
│   └── 子目录/
│       └── index.html
├── metadata.json              # 元数据存储
└── logs/
    └── webapps.log            # 日志文件
```

### 3.3 API 设计

#### 管理员接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/status` | 获取登录状态 |
| POST | `/api/admin/setup` | 创建首个管理员 |
| POST | `/api/admin/login` | 管理员登录 |
| POST | `/api/admin/logout` | 管理员登出 |
| GET | `/api/admin/users` | 获取管理员列表 |
| POST | `/api/admin/users` | 添加管理员 |
| DELETE | `/api/admin/users/<username>` | 删除管理员 |
| POST | `/api/admin/password` | 修改密码 |

#### 文件接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/files` | 获取文件列表 |
| POST | `/api/files/upload` | 上传文件 |
| PUT | `/api/files/<key>` | 更新文件信息 |
| DELETE | `/api/files/<key>` | 删除文件 |
| POST | `/api/files/<key>/password` | 验证密码 |

#### 系统接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 获取服务器状态 |
| GET | `/api/logs` | 获取日志列表 |
| GET | `/logs` | 日志查看页面 |

### 3.4 数据结构

#### metadata.json 结构

```json
{
  "file:example.html": {
    "title": "示例页面",
    "description": "这是一个示例",
    "uploader_ip": "192.168.1.100",
    "upload_time": "2026-06-26T17:00:00",
    "original_name": "example.html",
    "product_line": "老板云",
    "password": "123456"
  },
  "_system_admins_": {
    "users": [
      {
        "username": "admin",
        "password_hash": "sha256哈希值",
        "created_at": "2026-06-26T17:00:00"
      }
    ]
  }
}
```

#### 文件 Key 规则

- 根目录文件：`file:example.html`
- 子目录文件：`file:子目录名/index.html`

---

## 4. 部署说明

### 4.1 环境要求

- Python 3.8+
- Node.js 16+ (开发/构建前端时需要)
- 网络可达（默认 0.0.0.0:8080）

### 4.2 启动步骤

1. **安装依赖**
```bash
pip install flask
cd frontend && npm install
```

2. **构建前端**（如有修改）
```bash
cd frontend && npm run build
```

3. **启动服务**
```bash
cd server && python3 app.py
```

4. **访问**
- 管理界面：http://localhost:8080/
- 文件访问：http://localhost:8080/files/文件名

### 4.3 初始配置

1. 首次访问时创建超级管理员账户
2. 默认超级管理员：谢勇华 / xyh123456

---

## 5. 开发规范

### 5.1 代码提交流程

1. **开发自测**：每次代码修改后，必须对**所有受影响的功能**进行全面测试
2. **测试清单**：针对每个改动，列出可能影响的功能点，逐项验证
3. **回归测试**：确保新改动不破坏已有功能
4. **复测确认**：发现 Bug → 修复 → 再次完整测试 → 确认通过后再交付

### 5.2 受影响功能快速检测清单

| 改动范围 | 必须测试的功能点 |
|---------|----------------|
| 后端 API 改动 | API 响应格式、错误处理、权限校验、Cookie 设置 |
| 前端认证流程 | 登录/登出、会话保持、Token 管理 |
| 文件访问改动 | 无密码访问、有密码访问、会话复用、错误密码拒绝 |
| 文件上传改动 | HTML 上传、ZIP 上传、文件列表刷新、重复上传 |
| 管理功能改动 | 管理员登录、添加/删除用户、修改密码、日志查看 |

### 5.3 API 测试命令参考

```bash
# 基础测试
curl -s http://localhost:8080/api/status
curl -s http://localhost:8080/api/files
curl -s http://localhost:8080/api/admin/status

# 文件访问测试
curl -s "http://localhost:8080/api/files/<key>/session"
curl -s "http://localhost:8080/api/files/<key>/password" -X POST -H "Content-Type: application/json" -d '{"password":"xxx"}'
curl -s -b cookies.txt "http://localhost:8080/protected/<filename>"

# 认证流程测试
curl -s "http://localhost:8080/api/admin/login" -X POST -H "Content-Type: application/json" -d '{"username":"xxx","password":"xxx"}'
```

---

## 6. 版本信息

- 当前版本：参见 config.py 中的 VERSION
- 版本号格式：主版本.迭代号 (如 1.0.1)

---

## 7. 附录

### 6.1 IP 获取说明

系统通过以下顺序获取客户端 IP：
1. `X-Forwarded-For` 请求头
2. `X-Real-IP` 请求头
3. `request.remote_addr`

### 6.2 密码安全

- 管理员密码使用 SHA256 哈希存储
- 文件访问令牌使用 secrets.token_urlsafe 生成

### 6.3 文件大小限制

- 最大上传文件：100MB
