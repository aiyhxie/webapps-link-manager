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
import changelog
import audit

# Minimal logger for internal warnings/errors (not the audit trail)
logger = logging.getLogger("webapps")
logger.setLevel(logging.WARNING)
logger.addHandler(logging.StreamHandler())

# In-memory token store: token -> {filename}
# (No password stored — token is proof of prior password verification)
_access_tokens: Dict[str, Dict] = {}

# In-memory admin session store: token -> username
_admin_sessions: Dict[str, str] = {}

# One-time short-lived log viewer tokens: token -> expiry timestamp
def _safe_cookie_name(filename: str) -> str:
    """Generate an ASCII-safe, stable cookie name from a (possibly non-ASCII)
    filename. Cookie names must be ASCII; filenames containing Chinese or other
    non-ASCII chars would otherwise be mangled by the HTTP layer and break the
    access-token round-trip. Hashing yields a deterministic ASCII-only name."""
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:32]
    return f"file_token_{digest}"


def create_app():
    app = Flask(__name__, template_folder="templates")
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB max upload

    # Keep PRD.md changelog table in sync with changelog.json on startup
    try:
        changelog.sync_prd_changelog()
    except Exception as e:
        logger.warning(f"PRD changelog sync failed on startup: {e}")

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

    # ── Audit logging helpers ────────────────────────────────────────────────────

    def _project_title(key: str) -> str:
        """Resolve a human-friendly project title from its key; fallback to key."""
        meta = metadata.get_file_meta(key)
        if meta and meta.get("title"):
            return meta["title"]
        return key[5:] if key.startswith("file:") else key

    def audit_admin(action: str, target: str = "", detail: str = "", actor: str = None):
        """Record a管理员 action (actor = admin name, plus source IP)."""
        audit.log("admin", action,
                  actor=(actor if actor is not None else get_current_admin()),
                  ip=get_client_ip(), target=target, detail=detail)

    def audit_project(action: str, key: str, detail: str = ""):
        """Record a project CRUD action. actor = admin name if logged in else IP."""
        admin = get_current_admin()
        ip = get_client_ip()
        audit.log("project", action, actor=(admin or ip), ip=ip,
                  target=_project_title(key), detail=detail)

    def audit_access(key: str, detail: str = ""):
        """Record a project-level access (actor = viewer IP)."""
        ip = get_client_ip()
        audit.log("access", "查看项目", actor=ip, ip=ip,
                  target=_project_title(key), detail=detail)

    def _project_key_for_path(filename: str):
        """Return the project key if `filename` is a project ENTRY (root .html or
        <dir>/index.html), else None — so static assets/sub-pages aren't logged."""
        if not filename or ".." in filename:
            return None
        parts = filename.split("/")
        if len(parts) == 1 and filename.lower().endswith(".html"):
            return f"file:{filename}"          # root-level project
        if len(parts) == 2 and parts[1].lower() == "index.html":
            return f"file:{filename}"          # first-level folder project entry
        return None

    # ── API Routes ──────────────────────────────────────────────────────────────

    @app.route("/api/admin/status", methods=["GET"])
    def admin_status():
        """Get admin login status."""
        username = get_current_admin()
        is_super = is_super_admin_user()
        # Check if any admins exist
        admins = metadata.get_admins()
        has_admins = len(admins) > 0
        must_change = metadata.must_change_password(username) if username else False
        return jsonify({
            "success": True,
            "isLoggedIn": bool(username),
            "username": username,
            "isSuperAdmin": is_super,
            "hasAdmins": has_admins,
            "mustChangePassword": must_change,
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

        pwd_hash = metadata.hash_admin_password(password)
        if metadata.add_admin(username, pwd_hash, force_password_change=True):
            audit_admin("创建超级管理员", target=username, actor=username)
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
            must_change = metadata.must_change_password(username)
            audit_admin("登录", detail=("超级管理员" if is_super else "普通管理员"), actor=username)
            return jsonify({
                "success": True,
                "message": "登录成功",
                "token": token,
                "username": username,
                "isSuperAdmin": is_super,
                "mustChangePassword": must_change,
            })
        else:
            audit_admin("登录失败", target=username, detail="用户名或密码错误", actor=username)
            return jsonify({"success": False, "message": "用户名或密码错误"}), 401

    @app.route("/api/admin/logout", methods=["POST"])
    def admin_logout():
        """Admin logout."""
        token = request.headers.get("X-Admin-Token", "")
        if token in _admin_sessions:
            username = _admin_sessions[token]
            del _admin_sessions[token]
            audit_admin("退出登录", actor=username)
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

        pwd_hash = metadata.hash_admin_password(password)
        if metadata.add_admin(username, pwd_hash):
            audit_admin("添加管理员", target=username)
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
            audit_admin("删除管理员", target=username, actor=current_user)
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

        if old_password == new_password:
            return jsonify({"success": False, "message": "新密码不能与旧密码相同"}), 400

        username = get_current_admin()
        if not metadata.verify_admin_password(username, old_password):
            return jsonify({"success": False, "message": "旧密码错误"}), 400

        new_hash = metadata.hash_admin_password(new_password)
        if metadata.update_admin_password(username, new_hash):
            metadata.clear_force_password_change(username)
            audit_admin("修改密码", actor=username)
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
                for k in (keys or []):
                    audit_project("新建项目", k, detail=f"ZIP上传 {original_filename}")
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
                audit_project("新建项目", key, detail=f"HTML上传 {safe_name}")
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
            audit_project("设置密码" if password else "清除密码", key)
        elif title is not None or description is not None or product_line is not None:
            audit_project("编辑信息", key)

        return jsonify({"success": True, "message": "已更新"})

    @app.route("/api/files/<path:key>/versions", methods=["GET"])
    def get_versions(key):
        """Get all versions for a file."""
        meta = metadata.get_file_meta(key)
        if not meta:
            return jsonify({"success": False, "message": "文件不存在"}), 404
        versions_info = metadata.get_versions(key)
        return jsonify({
            "success": True,
            "data": versions_info,
        })

    @app.route("/api/files/<path:key>/versions", methods=["POST"])
    def upload_new_version(key):
        """Upload a new version for an existing file."""
        client_ip = get_client_ip()

        # Resolve filename from key once
        filename = key[5:] if key.startswith("file:") else key

        # Check permission - allow if can_delete OR admin OR file has no metadata (legacy file)
        has_meta = metadata.get_file_meta(key) is not None
        has_physical = (WEBAPPS_DIR / filename).exists()
        if not has_meta and not has_physical:
            return jsonify({"success": False, "message": "文件不存在"}), 404
        if has_meta and not file_manager.can_delete(key, client_ip) and not get_current_admin():
            return jsonify({"success": False, "message": "无权更新此项目"}), 403

        if "file" not in request.files:
            return jsonify({"success": False, "message": "没有上传文件"}), 400

        upload_file = request.files["file"]
        if upload_file.filename == "":
            return jsonify({"success": False, "message": "文件名为空"}), 400

        original_lower = upload_file.filename.lower()

        if not (original_lower.endswith(".zip") or original_lower.endswith(".html")):
            return jsonify({"success": False, "message": "只支持 HTML 或 ZIP 文件"}), 400

        file_data = upload_file.read()

        if original_lower.endswith(".zip"):
            # Handle ZIP: extract and update version
            success, msg, _ = file_manager.extract_zip_for_version(file_data, filename, client_ip)
            if success:
                versions_info = metadata.get_versions(key)
                current_v = versions_info.get("current_version", "V1")
                audit_project("上传新版本", key, detail=f"ZIP -> {current_v}")
                return jsonify({"success": True, "message": msg, "version": current_v})
            else:
                return jsonify({"success": False, "message": msg}), 400
        else:
            # Handle HTML: archive old content and save new (in place, preserving
            # the project's real nested path derived from its key)
            success, message, _ = file_manager.update_file_version(key, file_data, client_ip)
            if success:
                versions_info = metadata.get_versions(key)
                current_v = versions_info.get("current_version", "V1")
                audit_project("上传新版本", key, detail=f"-> {current_v}")
                return jsonify({"success": True, "message": message, "version": current_v})
            else:
                return jsonify({"success": False, "message": message}), 400

    @app.route("/api/files/<path:key>/versions/<version>/restore", methods=["PUT"])
    def restore_version(key, version):
        """Restore a historical version as the current version."""
        client_ip = get_client_ip()
        admin_user = get_current_admin()

        if not file_manager.can_delete(key, client_ip) and not admin_user:
            return jsonify({"success": False, "message": "无权恢复此版本"}), 403

        success, message = file_manager.restore_version_file(key, version, client_ip)
        if success:
            audit_project("恢复版本", key, detail=f"-> {version}")
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400

    @app.route("/api/files/<path:key>/versions/<version>", methods=["DELETE"])
    def delete_version(key, version):
        """Delete a historical version."""
        client_ip = get_client_ip()
        admin_user = get_current_admin()

        if not file_manager.can_delete(key, client_ip) and not admin_user:
            return jsonify({"success": False, "message": "无权删除此版本"}), 403

        success, message = file_manager.delete_version_file(key, version, client_ip)
        if success:
            audit_project("删除版本", key, detail=f"{version}")
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400

    @app.route("/api/files/<path:key>", methods=["DELETE"])
    def delete_file(key):
        """Delete a file (requires IP match)."""
        client_ip = get_client_ip()
        admin_user = get_current_admin()
        success, message = file_manager.delete_file(key, client_ip)

        if success:
            audit_project("删除项目", key)
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
            # Read live from changelog.json so newly recorded versions show
            # without needing a server restart.
            "version": changelog.get_latest_version(),
        })

    @app.route("/api/changelog", methods=["GET"])
    def get_changelog():
        """Get all changelog entries (newest first)."""
        entries = changelog.get_changelog_entries()
        return jsonify({
            "success": True,
            "data": entries,
            "current_version": VERSION,
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

        # Validate token: check it exists and matches the filename
        is_valid = False
        if token and token in _access_tokens:
            token_data = _access_tokens[token]
            if token_data["filename"] == filename:
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
            # Store token (no password stored — token itself grants access)
            _access_tokens[token] = {
                "filename": filename,
            }
            # Note: the actual project view is logged when /protected serves the
            # entry page, so we don't log password verification separately here.
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
            return jsonify({"success": False, "message": "密码错误"}), 401

    # ── Log Viewing ──────────────────────────────────────────────────────────────

    @app.route("/api/logs", methods=["GET"])
    def get_logs():
        """Get audit log entries (structured). Requires a valid admin session
        token via X-Admin-Token header. Supports filtering:
          - q:        keyword substring (action/target/detail/actor/ip/category)
          - actor:    operator filter (matches admin name OR IP)
          - category: project | admin | access
        """
        admin_token = request.headers.get("X-Admin-Token", "")
        if not admin_token or admin_token not in _admin_sessions:
            return jsonify({"success": False, "message": "未登录"}), 401

        q = request.args.get("q", "")
        actor = request.args.get("actor", "")
        category = request.args.get("category", "")
        try:
            entries = audit.query(q=q, actor=actor, category=category, limit=1000)
            return jsonify({"success": True, "logs": entries})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route("/logs", methods=["GET"])
    def view_logs():
        """Serve the log viewer page shell.

        The shell contains no sensitive data — the real authorization boundary
        is /api/logs, which requires a valid admin session token sent as the
        X-Admin-Token header. The page's JS reads the token from same-origin
        localStorage, so no token is ever placed in the URL.
        """
        return """
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="utf-8">
            <title>系统日志 - WebApps</title>
            <style>
                * { box-sizing: border-box; margin: 0; padding: 0; }
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1e1e1e; color: #d4d4d4; min-height: 100vh; }
                .header { background: #323232; padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #404040; position: sticky; top: 0; z-index: 5; }
                .header h1 { color: #fff; font-size: 18px; }
                .btn { background: #0e639c; color: #fff; border: none; padding: 7px 16px; border-radius: 4px; cursor: pointer; font-size: 13px; }
                .btn:hover { background: #1177bb; }
                .filter-bar { background: #2a2a2a; padding: 12px 24px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; border-bottom: 1px solid #404040; position: sticky; top: 51px; z-index: 4; }
                .filter-bar input, .filter-bar select { background: #3c3c3c; border: 1px solid #555; color: #d4d4d4; padding: 6px 10px; border-radius: 4px; font-size: 13px; }
                .filter-bar input { width: 220px; }
                .filter-bar .hint { color: #777; font-size: 12px; margin-left: auto; }
                .wrap { padding: 16px 24px; }
                table { width: 100%; border-collapse: collapse; font-size: 13px; }
                th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #333; vertical-align: top; }
                th { color: #9aa0a6; font-weight: 500; position: sticky; top: 96px; background: #1e1e1e; }
                tr:hover td { background: #262626; }
                .time { color: #858585; white-space: nowrap; font-variant-numeric: tabular-nums; }
                .cat { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; white-space: nowrap; }
                .cat.project { background: rgba(78,201,176,.15); color: #4ec9b0; }
                .cat.admin { background: rgba(86,156,214,.15); color: #569cd6; }
                .cat.access { background: rgba(206,145,120,.15); color: #ce9178; }
                .actor { color: #dcdcaa; }
                .ip { color: #9aa0a6; font-family: 'Consolas','Monaco',monospace; white-space: nowrap; }
                .action { color: #e8eaed; }
                .action.danger { color: #f14c4c; }
                .target { color: #cbd5e1; word-break: break-all; }
                .detail { color: #777; }
                .empty { text-align: center; padding: 60px; color: #666; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📋 系统操作日志</h1>
                <button class="btn" onclick="loadLogs()">🔄 刷新</button>
            </div>
            <div class="filter-bar">
                <input type="text" id="q" placeholder="按关键字搜索…" oninput="debouncedLoad()">
                <input type="text" id="actor" placeholder="按操作者搜索（IP 或 管理员姓名）" oninput="debouncedLoad()">
                <select id="category" onchange="loadLogs()">
                    <option value="">全部类别</option>
                    <option value="project">项目增删改</option>
                    <option value="admin">管理员动作</option>
                    <option value="access">访问记录</option>
                </select>
                <span class="hint" id="count"></span>
            </div>
            <div class="wrap" id="wrap">
                <div class="empty">加载中…</div>
            </div>
            <script>
                const CAT_NAME = { project: '项目', admin: '管理员', access: '访问' };
                let _timer = null;
                function debouncedLoad() { clearTimeout(_timer); _timer = setTimeout(loadLogs, 300); }
                function esc(s) {
                    return String(s == null ? '' : s)
                        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
                        .replace(/"/g,'&quot;');
                }
                async function loadLogs() {
                    const wrap = document.getElementById('wrap');
                    const adminTok = localStorage.getItem('adminToken') || '';
                    if (!adminTok) { wrap.innerHTML = '<div class="empty">请先在首页登录管理员账号，再打开本页面</div>'; return; }
                    const q = document.getElementById('q').value.trim();
                    const actor = document.getElementById('actor').value.trim();
                    const category = document.getElementById('category').value;
                    const params = new URLSearchParams();
                    if (q) params.set('q', q);
                    if (actor) params.set('actor', actor);
                    if (category) params.set('category', category);
                    try {
                        const resp = await fetch('/api/logs?' + params.toString(), { headers: { 'X-Admin-Token': adminTok } });
                        if (resp.status === 401) { wrap.innerHTML = '<div class="empty">会话已过期，请回首页重新登录管理员账号</div>'; return; }
                        const data = await resp.json();
                        if (data.success && Array.isArray(data.logs)) { render(data.logs); }
                        else { wrap.innerHTML = '<div class="empty">' + esc(data.message || '加载失败') + '</div>'; }
                    } catch(e) {
                        wrap.innerHTML = '<div class="empty">加载失败: ' + esc(e.message) + '</div>';
                    }
                }
                function fmtTime(t) { return String(t || '').replace('T', ' '); }
                function render(logs) {
                    const wrap = document.getElementById('wrap');
                    document.getElementById('count').textContent = '共 ' + logs.length + ' 条';
                    if (!logs.length) { wrap.innerHTML = '<div class="empty">暂无匹配的日志记录</div>'; return; }
                    let rows = logs.map(function(e) {
                        const cat = e.category || '';
                        const danger = /删除|失败/.test(e.action || '') ? ' danger' : '';
                        return '<tr>' +
                            '<td class="time">' + esc(fmtTime(e.time)) + '</td>' +
                            '<td><span class="cat ' + esc(cat) + '">' + esc(CAT_NAME[cat] || cat) + '</span></td>' +
                            '<td class="actor">' + esc(e.actor) + '</td>' +
                            '<td class="ip">' + esc(e.ip) + '</td>' +
                            '<td class="action' + danger + '">' + esc(e.action) + '</td>' +
                            '<td class="target">' + esc(e.target) + '</td>' +
                            '<td class="detail">' + esc(e.detail) + '</td>' +
                        '</tr>';
                    }).join('');
                    wrap.innerHTML = '<table><thead><tr>' +
                        '<th>时间</th><th>类别</th><th>操作者</th><th>来源IP</th><th>操作</th><th>项目/对象</th><th>备注</th>' +
                        '</tr></thead><tbody>' + rows + '</tbody></table>';
                }
                loadLogs();
            </script>
        </body>
        </html>
        """

    # ── Static File Serving ──────────────────────────────────────────────────────

    @app.route("/files/<path:filename>")
    def serve_file(filename):
        """Serve files from webapps directory."""
        # Only log project-level entry views (not static assets/sub-pages)
        pkey = _project_key_for_path(filename)
        if pkey:
            audit_access(pkey)
        return send_from_directory(WEBAPPS_DIR, filename)

    @app.route("/protected/<path:filename>")
    def serve_protected_file(filename):
        """Serve password-protected files using HttpOnly cookie token."""
        key = f"file:{filename}"
        meta = metadata.get_file_meta(key)

        if not meta or not meta.get("password"):
            # No password required, serve normally
            pkey = _project_key_for_path(filename)
            if pkey:
                audit_access(pkey)
            return send_from_directory(WEBAPPS_DIR, filename)

        # Check token from cookie (secure, not in URL)
        cookie_name = _safe_cookie_name(filename)
        token = request.cookies.get(cookie_name, "")

        # Validate token
        is_valid_token = False
        if token and token in _access_tokens:
            token_data = _access_tokens[token]
            if token_data["filename"] == filename:
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

        pkey = _project_key_for_path(filename)
        if pkey:
            audit_access(pkey)
        return send_from_directory(WEBAPPS_DIR, filename)

    @app.route("/assets/<path:filename>")
    def serve_assets(filename):
        """Serve static assets (JS/CSS) from templates/assets/."""
        assets_dir = Path(__file__).parent / "templates" / "assets"
        return send_from_directory(assets_dir, filename)

    @app.route("/versions/<path:filename>/<version>")
    def serve_version(filename, version):
        """Serve a historical version of a file."""
        key = f"file:{filename}"

        # Check password protection
        meta = metadata.get_file_meta(key)
        if meta and meta.get("password"):
            # Check if user has valid cookie for this file
            cookie_name = _safe_cookie_name(filename)
            token = request.cookies.get(cookie_name, "")
            is_valid_token = False
            if token and token in _access_tokens:
                token_data = _access_tokens[token]
                if token_data["filename"] == filename:
                    is_valid_token = True
            if not is_valid_token:
                return """
                <!DOCTYPE html>
                <html><head><meta charset="utf-8"><title>需要密码访问</title></head>
                <body style="font-family:sans-serif;text-align:center;padding:60px;">
                <h2>🔒 此文件已加密，请从主页输入密码后访问</h2>
                <p><a href="/">返回首页</a></p></body></html>
                """, 401

        # Try historical version first
        content = file_manager.get_version_content(filename, version)
        if content is not None:
            audit_access(key, detail=f"历史版本 {version}")
            return content, 200, {"Content-Type": "text/html; charset=utf-8"}

        # Fall back to current version
        content = file_manager.get_current_content(filename)
        if content is not None:
            audit_access(key, detail=f"请求{version}，返回当前版本")
            return content, 200, {"Content-Type": "text/html; charset=utf-8"}

        return "文件不存在", 404

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
