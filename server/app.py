"""
WebApps Link Manager - Flask Server

功能说明：
- 文件服务：提供 webapps/ 目录下 HTML 文件的访问
- 文件管理 API：列表、上传、更新、删除
- 管理员系统：登录、权限管理、日志查看
- 密码保护：基于令牌的文件访问控制
- 日志系统：记录管理员操作和文件操作

数据结构：
- metadata.json: 存储文件元数据（标题、描述、上传者IP、密码）和管理员信息
- logs/webapps.log: 操作日志文件

API 路由：
- GET  /api/files           - 获取文件列表
- POST /api/files/upload    - 上传文件（HTML 或 ZIP）
- PUT  /api/files/<key>     - 更新文件信息
- DELETE /api/files/<key>   - 删除文件
- POST /api/files/<key>/password - 验证文件密码
- GET  /api/admin/status    - 获取管理员状态
- POST /api/admin/login     - 管理员登录
- POST /api/admin/logout    - 管理员登出
- GET  /api/admin/users     - 获取管理员列表
- POST /api/admin/users     - 添加管理员
- DELETE /api/admin/users/<username> - 删除管理员
- POST /api/admin/password  - 修改密码
- GET  /api/logs            - 获取日志列表
- GET  /logs                - 日志查看页面
"""

import sys
import json
import secrets
import hashlib
import logging
from pathlib import Path
from typing import Dict

from flask import (
    Flask, request, jsonify, send_from_directory,
    send_file
)

# Add server directory to path for imports
_server_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(_server_dir))

from config import WEBAPPS_DIR, HOST, PORT, VERSION
import metadata
import file_manager

# Setup logging
LOG_DIR = _server_dir.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "webapps.log"

# Configure logger
logger = logging.getLogger("webapps")
logger.setLevel(logging.INFO)
handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger.addHandler(handler)

def log_admin_action(username: str, action: str, detail: str = ""):
    """Log admin actions."""
    if detail:
        logger.info(f"ADMIN [{username}] {action}: {detail}")
    else:
        logger.info(f"ADMIN [{username}] {action}")

def log_file_action(action: str, detail: str):
    """Log file actions."""
    logger.info(f"FILE {action}: {detail}")

# In-memory token store: token -> {password, filename, expires_at}
_access_tokens: Dict[str, Dict] = {}

# In-memory admin session store: token -> username
_admin_sessions: Dict[str, str] = {}


def _safe_cookie_name(filename: str) -> str:
    """Generate a safe cookie name from filename - replaces / with _ to avoid cookie parsing issues."""
    return f"file_token_{filename.replace('/', '_')}"


def create_app():
    app = Flask(__name__, template_folder="templates")
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB max upload

    def get_client_ip():
        """Get client IP from headers or remote_addr."""
        ip = request.headers.get("X-Forwarded-For")
        if ip:
            return ip.split(",")[0].strip()
        return request.headers.get("X-Real-IP", request.remote_addr or "127.0.0.1")

    def get_current_admin():
        """Get current admin username from session token."""
        token = request.headers.get("X-Admin-Token", "")
        return _admin_sessions.get(token, "")

    def is_admin_logged_in():
        """Check if admin is logged in."""
        return bool(get_current_admin())

    def is_super_admin_user():
        """Check if current admin is super admin."""
        username = get_current_admin()
        return metadata.is_super_admin(username) if username else False

    # ── API Routes ──────────────────────────────────────────────────────────────

    @app.route("/api/admin/status", methods=["GET"])
    def admin_status():
        """Get admin login status."""
        username = get_current_admin()
        is_super = is_super_admin_user()
        # Check if any admins exist
        admins = metadata.get_admins()
        has_admins = len(admins) > 0
        return jsonify({
            "success": True,
            "isLoggedIn": bool(username),
            "username": username,
            "isSuperAdmin": is_super,
            "hasAdmins": has_admins,
        })

    @app.route("/api/admin/setup", methods=["POST"])
    def admin_setup():
        """Setup initial admin (only works if no admins exist)."""
        admins = metadata.get_admins()
        if len(admins) > 0:
            return jsonify({"success": False, "message": "系统已有管理员，请登录"}), 400

        data = request.get_json()
        username = data.get("username", "")
        password = data.get("password", "")

        if not username or not password:
            return jsonify({"success": False, "message": "请输入用户名和密码"}), 400

        if len(username) < 2 or len(password) < 6:
            return jsonify({"success": False, "message": "用户名至少2字符，密码至少6字符"}), 400

        import hashlib
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        if metadata.add_admin(username, pwd_hash):
            log_admin_action(username, "创建超级管理员")
            return jsonify({"success": True, "message": "管理员创建成功，请登录"})
        else:
            return jsonify({"success": False, "message": "创建失败"}), 500

    @app.route("/api/admin/login", methods=["POST"])
    def admin_login():
        """Admin login."""
        data = request.get_json()
        username = data.get("username", "")
        password = data.get("password", "")

        if not username or not password:
            return jsonify({"success": False, "message": "请输入用户名和密码"}), 400

        if metadata.verify_admin_password(username, password):
            token = secrets.token_urlsafe(32)
            _admin_sessions[token] = username
            is_super = metadata.is_super_admin(username)
            log_admin_action(username, "登录", f"超级管理员" if is_super else "普通管理员")
            return jsonify({
                "success": True,
                "message": "登录成功",
                "token": token,
                "username": username,
                "isSuperAdmin": is_super,
            })
        else:
            client_ip = get_client_ip()
            logger.warning(f"LOGIN FAILED | 用户名: {username} | IP: {client_ip}")
            return jsonify({"success": False, "message": "用户名或密码错误"}), 401

    @app.route("/api/admin/logout", methods=["POST"])
    def admin_logout():
        """Admin logout."""
        token = request.headers.get("X-Admin-Token", "")
        if token in _admin_sessions:
            username = _admin_sessions[token]
            del _admin_sessions[token]
            log_admin_action(username, "退出登录")
        return jsonify({"success": True, "message": "已退出登录"})

    @app.route("/api/admin/users", methods=["GET"])
    def admin_list():
        """List all admin users (super admin only)."""
        if not is_admin_logged_in():
            return jsonify({"success": False, "message": "未登录"}), 401
        if not is_super_admin_user():
            return jsonify({"success": False, "message": "权限不足"}), 403

        users = metadata.get_admins()
        return jsonify({"success": True, "data": users})

    @app.route("/api/admin/users", methods=["POST"])
    def admin_add():
        """Add a new admin user (super admin only)."""
        if not is_admin_logged_in():
            return jsonify({"success": False, "message": "未登录"}), 401
        if not is_super_admin_user():
            return jsonify({"success": False, "message": "权限不足"}), 403

        data = request.get_json()
        username = data.get("username", "")
        password = data.get("password", "")

        if not username or not password:
            return jsonify({"success": False, "message": "请输入用户名和密码"}), 400

        if len(username) < 2 or len(password) < 6:
            return jsonify({"success": False, "message": "用户名至少2字符，密码至少6字符"}), 400

        import hashlib
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        if metadata.add_admin(username, pwd_hash):
            log_admin_action(get_current_admin(), "添加管理员", username)
            return jsonify({"success": True, "message": "管理员添加成功"})
        else:
            return jsonify({"success": False, "message": "用户名已存在"}), 400

    @app.route("/api/admin/users/<username>", methods=["DELETE"])
    def admin_delete(username):
        """Delete an admin user (super admin only, cannot delete self)."""
        if not is_admin_logged_in():
            return jsonify({"success": False, "message": "未登录"}), 401
        if not is_super_admin_user():
            return jsonify({"success": False, "message": "权限不足"}), 403

        current_user = get_current_admin()
        if current_user == username:
            return jsonify({"success": False, "message": "不能删除自己"}), 400

        if metadata.remove_admin(username):
            # Also logout if the deleted user is currently logged in
            for token, uname in list(_admin_sessions.items()):
                if uname == username:
                    del _admin_sessions[token]
            log_admin_action(current_user, "删除管理员", username)
            return jsonify({"success": True, "message": "管理员已删除"})
        else:
            return jsonify({"success": False, "message": "管理员不存在"}), 404

    @app.route("/api/admin/password", methods=["POST"])
    def admin_change_password():
        """Change own password (any logged-in admin)."""
        if not is_admin_logged_in():
            return jsonify({"success": False, "message": "未登录"}), 401

        data = request.get_json()
        old_password = data.get("oldPassword", "")
        new_password = data.get("newPassword", "")

        if not old_password or not new_password:
            return jsonify({"success": False, "message": "请输入旧密码和新密码"}), 400

        if len(new_password) < 6:
            return jsonify({"success": False, "message": "新密码至少6字符"}), 400

        username = get_current_admin()
        if not metadata.verify_admin_password(username, old_password):
            return jsonify({"success": False, "message": "旧密码错误"}), 400

        new_hash = hashlib.sha256(new_password.encode()).hexdigest()
        if metadata.update_admin_password(username, new_hash):
            log_admin_action(username, "修改密码")
            return jsonify({"success": True, "message": "密码已更新"})
        else:
            return jsonify({"success": False, "message": "密码更新失败"}), 500

    @app.route("/api/files", methods=["GET"])
    def list_files():
        """List all files with metadata."""
        files = file_manager.scan_webapps()
        client_ip = get_client_ip()
        admin_user = get_current_admin()

        # Add canDelete flag based on IP or admin status
        for f in files:
            f["canDelete"] = file_manager.can_delete(f["key"], client_ip) or bool(admin_user)

        return jsonify({
            "success": True,
            "data": files,
            "baseUrl": f"http://{file_manager.get_local_ip()}:{PORT}",
        })

    @app.route("/api/files/upload", methods=["POST"])
    def upload_file():
        """Handle file or zip upload."""
        client_ip = get_client_ip()

        if "file" not in request.files:
            return jsonify({"success": False, "message": "没有上传文件"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "message": "文件名为空"}), 400

        original_filename = file.filename
        # Check file type based on original filename extension (case-insensitive)
        original_lower = original_filename.lower()

        # Determine if it's a zip or html
        if original_lower.endswith(".zip"):
            zip_data = file.read()
            success, message, keys = file_manager.extract_zip(zip_data, client_ip)
            if success:
                log_file_action("上传ZIP", f"{original_filename} -> {keys}")
                return jsonify({"success": True, "message": message, "keys": keys})
            else:
                return jsonify({"success": False, "message": message}), 400

        elif original_lower.endswith(".html"):
            # For HTML files, preserve the original filename but sanitize for path traversal
            # Only allow alphanumeric, Chinese chars, spaces, dashes, underscores, dots, and parentheses
            import re
            # Keep Chinese chars and common filename chars, remove path traversal attempts
            safe_name = re.sub(r'[^\w\s\u4e00-\u9fff.\-()（）]', '', original_filename)
            safe_name = safe_name.strip()
            # Ensure it ends with .html (case-insensitive check already done)
            if not safe_name.lower().endswith(".html"):
                safe_name = safe_name + ".html"
            file_data = file.read()
            success, message, key = file_manager.upload_file(file_data, safe_name, client_ip)
            if success:
                log_file_action("上传HTML", f"{safe_name} by IP {client_ip}")
                return jsonify({"success": True, "message": message, "key": key})
            else:
                return jsonify({"success": False, "message": message}), 400

        else:
            return jsonify({"success": False, "message": "只支持 HTML 或 ZIP 文件"}), 400

    @app.route("/api/files/<path:key>", methods=["PUT"])
    def update_file(key):
        """Update file title, description, and/or product_line."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "无效的请求数据"}), 400

        title = data.get("title")
        description = data.get("description")
        product_line = data.get("productLine")
        password = data.get("password")

        if title is None and description is None and product_line is None and password is None:
            return jsonify({"success": False, "message": "没有提供要更新的字段"}), 400

        # Check if key exists
        existing = metadata.get_file_meta(key)
        if not existing:
            # Create metadata entry for file without metadata
            if key.startswith("file:"):
                rel_path = key[5:]
                file_path = WEBAPPS_DIR / rel_path
                if file_path.exists():
                    metadata.set_file_meta(
                        key=key,
                        title=title or file_path.name,
                        uploader_ip="",
                        description=description or "",
                        password=password,
                    )
                else:
                    return jsonify({"success": False, "message": "文件不存在"}), 404
            else:
                return jsonify({"success": False, "message": "文件不存在"}), 404
        else:
            metadata.update_file_meta(key, title, description, product_line, password)

        admin_user = get_current_admin()
        if password is not None:
            if admin_user:
                log_admin_action(admin_user, "设置密码" if password else "清除密码", f"{key}")
            else:
                log_file_action("设置密码" if password else "清除密码", f"{key}")
        elif admin_user:
            log_admin_action(admin_user, "编辑项目", f"{key}")
        elif title or description:
            log_file_action("编辑", f"{key}")

        return jsonify({"success": True, "message": "已更新"})

    @app.route("/api/files/<path:key>", methods=["DELETE"])
    def delete_file(key):
        """Delete a file (requires IP match)."""
        client_ip = get_client_ip()
        admin_user = get_current_admin()
        success, message = file_manager.delete_file(key, client_ip)

        if success:
            if admin_user:
                log_admin_action(admin_user, "删除项目", f"{key}")
            else:
                log_file_action("删除", f"{key} by IP {client_ip}")
            return jsonify({"success": True, "message": message})
        else:
            status = 403 if "无权" in message else 404 if "不存在" in message else 400
            return jsonify({"success": False, "message": message}), status

    @app.route("/api/status", methods=["GET"])
    def status():
        """Get server status."""
        return jsonify({
            "success": True,
            "status": "running",
            "ip": file_manager.get_local_ip(),
            "port": PORT,
            "webappsDir": str(WEBAPPS_DIR),
            "version": VERSION,
        })

    @app.route("/api/files/<path:key>/session", methods=["GET"])
    def check_file_session(key):
        """Check if the current session (cookie) has access to this protected file."""
        filename = key[5:] if key.startswith("file:") else key
        cookie_name = _safe_cookie_name(filename)
        token = request.cookies.get(cookie_name, "")

        meta = metadata.get_file_meta(key)
        has_password = bool(meta and meta.get("password"))

        if not has_password:
            return jsonify({"success": True, "hasAccess": True, "hasPassword": False})

        # Validate token against stored plain-text password (consistent with check_password)
        is_valid = False
        stored_password = meta.get("password", "")
        if token and token in _access_tokens:
            token_data = _access_tokens[token]
            # Compare plain-text password directly
            # Also check password hasn't changed since token was issued
            if (token_data["filename"] == filename and
                token_data["password"] == stored_password):
                is_valid = True

        return jsonify({"success": True, "hasAccess": is_valid, "hasPassword": has_password})

    @app.route("/api/files/<path:key>/password", methods=["POST"])
    def check_password(key):
        """Check if the provided password is correct and set HttpOnly cookie for access."""
        data = request.get_json()
        password = data.get("password", "") if data else ""

        if metadata.check_file_password(key, password):
            token = secrets.token_urlsafe(32)
            # Get filename from key
            filename = key[5:] if key.startswith("file:") else key
            # Store token permanently, bound to plain-text password (for consistent comparison)
            _access_tokens[token] = {
                "password": password,
                "filename": filename,
            }
            log_file_action("访问受保护文件", f"{key} - 密码验证成功")
            # Set HttpOnly cookie instead of returning token in response body
            resp = jsonify({"success": True, "message": "密码正确"})
            resp.set_cookie(
                _safe_cookie_name(filename),
                token,
                max_age=365 * 24 * 60 * 60,  # 1 year
                httponly=True,
                samesite="Lax",
                path="/"  # Must be / so both /api/* and /protected/* receive it
            )
            return resp
        else:
            log_file_action("访问受保护文件", f"{key} - 密码错误")
            return jsonify({"success": False, "message": "密码错误"}), 401

    # ── Log Viewing ──────────────────────────────────────────────────────────────

    @app.route("/api/logs", methods=["GET"])
    def get_logs():
        """Get recent log entries (admin only)."""
        # Support token from query param or header
        token = request.args.get("token", "") or request.headers.get("X-Admin-Token", "")
        if not token or token not in _admin_sessions:
            return jsonify({"success": False, "message": "未登录"}), 401

        try:
            if LOG_FILE.exists():
                lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
                # Return last 500 lines
                recent = lines[-500:] if len(lines) > 500 else lines
                return jsonify({"success": True, "logs": recent})
            else:
                return jsonify({"success": True, "logs": []})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route("/logs", methods=["GET"])
    def view_logs():
        """Serve log viewer page (admin only)."""
        # Check token from query param (for new tab access) or from session header
        token = request.args.get("token", "") or request.headers.get("X-Admin-Token", "")
        if not token or token not in _admin_sessions:
            return "<html><body style='font-family: sans-serif; text-align: center; padding: 60px;'><h1>请先登录管理员账号</h1><p>当前会话已过期或未登录</p><p><a href='/'>返回首页</a></p></body></html>", 401

        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>系统日志 - WebApps</title>
            <style>
                * { box-sizing: border-box; margin: 0; padding: 0; }
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1e1e1e; color: #d4d4d4; min-height: 100vh; }
                .header { background: #323232; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #404040; }
                .header h1 { color: #fff; font-size: 18px; }
                .header .btn { background: #0e639c; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
                .header .btn:hover { background: #1177bb; }
                .log-container { padding: 20px; }
                .log-entry { background: #252526; border: 1px solid #3c3c3c; border-radius: 4px; padding: 10px 14px; margin-bottom: 8px; font-family: 'Consolas', 'Monaco', monospace; font-size: 13px; line-height: 1.5; }
                .log-entry .time { color: #858585; margin-right: 12px; }
                .log-entry .level { margin-right: 12px; }
                .log-entry .level.INFO { color: #4ec9b0; }
                .log-entry .level.WARNING { color: #dcdcaa; }
                .log-entry .level.ERROR { color: #f14c4c; }
                .log-entry .admin { color: #569cd6; }
                .log-entry .file { color: #ce9178; }
                .log-entry .login-failed { color: #f14c4c; }
                .filter-bar { background: #323232; padding: 12px 24px; display: flex; gap: 12px; align-items: center; border-bottom: 1px solid #404040; }
                .filter-bar input { background: #3c3c3c; border: 1px solid #555; color: #d4d4d4; padding: 6px 12px; border-radius: 4px; width: 200px; }
                .filter-bar label { color: #ccc; display: flex; align-items: center; gap: 4px; cursor: pointer; }
                .empty { text-align: center; padding: 60px; color: #666; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📋 系统日志</h1>
                <button class="btn" onclick="refreshLogs()">🔄 刷新</button>
            </div>
            <div class="filter-bar">
                <input type="text" id="searchInput" placeholder="搜索日志内容..." onkeyup="filterLogs()">
                <label><input type="checkbox" id="filterAdmin" checked onchange="filterLogs()"> 管理员操作</label>
                <label><input type="checkbox" id="filterFile" checked onchange="filterLogs()"> 文件操作</label>
                <label><input type="checkbox" id="filterLogin" checked onchange="filterLogs()"> 登录记录</label>
            </div>
            <div class="log-container" id="logContainer">
                <div class="empty">加载中...</div>
            </div>
            <script>
                let allLogs = [];

                async function loadLogs() {
                    try {
                        const token = new URLSearchParams(window.location.search).get('token') || '';
                        const resp = await fetch('/api/logs' + (token ? '?token=' + encodeURIComponent(token) : ''), {
                            headers: token ? { 'X-Admin-Token': token } : {}
                        });
                        const data = await resp.json();
                        if (data.success && data.logs) {
                            allLogs = data.logs;
                            renderLogs(allLogs);
                        }
                    } catch(e) {
                        document.getElementById('logContainer').innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
                    }
                }

                function filterLogs() {
                    const search = document.getElementById('searchInput').value.toLowerCase();
                    const showAdmin = document.getElementById('filterAdmin').checked;
                    const showFile = document.getElementById('filterFile').checked;
                    const showLogin = document.getElementById('filterLogin').checked;

                    const filtered = allLogs.filter(log => {
                        if (search && !log.toLowerCase().includes(search)) return false;
                        if (log.includes('ADMIN') && !showAdmin) return false;
                        if ((log.includes('FILE') || log.includes('上传') || log.includes('删除') || log.includes('编辑')) && !showFile) return false;
                        if ((log.includes('登录') || log.includes('LOGIN') || log.includes('退出')) && !showLogin) return false;
                        return true;
                    });

                    renderLogs(filtered);
                }

                function renderLogs(logs) {
                    const container = document.getElementById('logContainer');
                    if (logs.length === 0) {
                        container.innerHTML = '<div class="empty">暂无日志记录</div>';
                        return;
                    }

                    container.innerHTML = logs.map(log => {
                        let level = 'INFO';
                        if (log.includes('WARNING')) level = 'WARNING';
                        if (log.includes('ERROR') || log.includes('FAILED')) level = 'ERROR';

                        // Format the log entry
                        let formatted = log;
                        formatted = formatted.replace(/\[([^\]]+)\]/g, '<span class="admin">[$1]</span>');
                        formatted = formatted.replace(/(FILE|上传|删除|编辑)/g, '<span class="file">$1</span>');
                        formatted = formatted.replace(/(LOGIN FAILED)/g, '<span class="login-failed">$1</span>');

                        return '<div class="log-entry"><span class="time">' + log.split('|')[0].trim() + '</span><span class="level ' + level + '">' + level + '</span>' + formatted + '</div>';
                    }).join('');
                }

                function refreshLogs() {
                    loadLogs();
                }

                // Load on init
                loadLogs();
                // Auto refresh every 10 seconds
                setInterval(loadLogs, 10000);
            </script>
        </body>
        </html>
        """

    # ── Static File Serving ──────────────────────────────────────────────────────

    @app.route("/files/<path:filename>")
    def serve_file(filename):
        """Serve files from webapps directory."""
        log_file_action("访问文件", filename)
        return send_from_directory(WEBAPPS_DIR, filename)

    @app.route("/protected/<path:filename>")
    def serve_protected_file(filename):
        """Serve password-protected files using HttpOnly cookie token."""
        key = f"file:{filename}"
        meta = metadata.get_file_meta(key)

        if not meta or not meta.get("password"):
            # No password required, serve normally
            log_file_action("访问文件", filename)
            return send_from_directory(WEBAPPS_DIR, filename)

        # Check token from cookie (secure, not in URL)
        cookie_name = _safe_cookie_name(filename)
        token = request.cookies.get(cookie_name, "")

        # Validate token
        is_valid_token = False
        if token and token in _access_tokens:
            token_data = _access_tokens[token]
            # Check filename and plain-text password match (consistent with check_password)
            if (token_data["filename"] == filename and
                token_data["password"] == meta["password"]):
                is_valid_token = True
                # Token remains valid for reuse

        if not is_valid_token:
            # Return password entry page
            return """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>需要密码访问</title>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #f5f5f5; }
                    .container { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); text-align: center; max-width: 400px; width: 90%; }
                    h2 { color: #333; margin-bottom: 20px; }
                    input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
                    button { width: 100%; padding: 12px; background: #4285f4; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
                    button:hover { background: #3367d6; }
                    .error { color: #ea4335; margin-top: 10px; display: none; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h2>🔒 此文件已加密</h2>
                    <p style="color: #666;">请输入访问密码</p>
                    <form method="POST" id="pwdForm">
                        <input type="password" name="password" id="pwdInput" placeholder="请输入密码" required />
                        <button type="submit">确认访问</button>
                    </form>
                    <p class="error" id="errorMsg">密码错误</p>
                </div>
                <script>
                document.getElementById('pwdForm').onsubmit = async function(e) {
                    e.preventDefault();
                    const pwd = document.getElementById('pwdInput').value;
                    try {
                        const resp = await fetch(window.location.pathname.replace('/protected/', '/api/files/file:') + '/password', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({password: pwd})
                        });
                        const data = await resp.json();
                        if (data.success) {
                            // Password correct, cookie is set by server via Set-Cookie header
                            // Reload to re-check cookie and serve the file
                            window.location.reload();
                        } else {
                            document.getElementById('errorMsg').style.display = 'block';
                        }
                    } catch(e) {
                        document.getElementById('errorMsg').style.display = 'block';
                    }
                };
                </script>
            </body>
            </html>
            """

        log_file_action("访问受保护文件", filename)
        return send_from_directory(WEBAPPS_DIR, filename)

    @app.route("/assets/<path:filename>")
    def serve_assets(filename):
        """Serve static assets (JS/CSS) from templates/assets/."""
        assets_dir = Path(__file__).parent / "templates" / "assets"
        return send_from_directory(assets_dir, filename)

    # ── SPA Fallback ─────────────────────────────────────────────────────────────

    @app.route("/", methods=["GET"])
    def index():
        """Serve the React app."""
        return send_file(Path(__file__).parent / "templates" / "index.html")

    return app


def main():
    app = create_app()
    local_ip = file_manager.get_local_ip()
    print(f"=" * 50)
    print(f"WebApps Link Manager 已启动")
    print(f"=" * 50)
    print(f"管理界面: http://{local_ip}:{PORT}/")
    print(f"文件目录: {WEBAPPS_DIR}")
    print(f"=" * 50)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
