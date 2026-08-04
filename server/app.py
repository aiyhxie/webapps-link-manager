"""
WebApps Link Manager - Flask Server

身份与权限（飞书 SSO 改造后）：
- 身份来自飞书扫码登录，会话持久化在 auth_sessions.json，重启不掉线
- embedded 形态：单进程直连，身份只从会话 Cookie 解析，客户端传入的
  X-Auth-* 头在 WSGI 层被删除
- gateway 形态：Nginx 做 auth_request 并注入 X-Auth-* 头，仅当对端在
  TRUSTED_GATEWAY_IPS 内才采信
- 项目所有权看 owner_id（飞书 UserID）；uploader_ip 降级为纯审计信息
- 管理员名单存在 metadata.json 的 _system_admin_list_，与飞书应用管理员解耦
- 应急管理员通道单独绑回环地址，飞书故障时兜底

数据存储：
- metadata.json  项目元数据 + 用户档案(_system_users_) + 管理员名单(_system_admin_list_)
                 + 应急账号(_system_admins_)
- auth_sessions.json  会话 / OAuth state / 跨域跳转凭证 / 应急失败计数
- logs/audit.jsonl    结构化审计日志

API 路由：
- GET    /api/me                      当前登录者身份与权限
- GET    /api/users                   用户档案列表（选人用）
- GET    /api/files                   项目列表（含 canManage / ownerId）
- POST   /api/files/upload            上传新项目
- PUT    /api/files/<key>             更新项目信息或密码
- DELETE /api/files/<key>             删除项目
- POST   /api/files/<key>/password    校验项目访问密码，签发访问凭证
- GET    /api/files/<key>/versions    版本列表
- POST   /api/files/<key>/versions    上传新版本
- PUT    /api/files/<key>/versions/<v>/restore   恢复版本
- DELETE /api/files/<key>/versions/<v>           删除版本
- POST   /api/projects/owner          批量指定负责人（超管）
- GET    /api/admins                  管理员名单
- POST   /api/admins                  添加普通管理员（超管）
- DELETE /api/admins/<user_id>        移除管理员（超管）
- GET    /api/logs                    审计日志查询
- GET    /api/status /api/changelog    系统信息
"""

import sys
import logging
from pathlib import Path

from flask import (
    Flask, request, jsonify, send_from_directory, send_file, g, redirect
)

# Add server directory to path for imports
_server_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(_server_dir))

import config
from config import WEBAPPS_DIR, HOST, PORT, VERSION
import metadata
import file_manager
import changelog
import audit
import permissions
import user_directory
from permissions import can_manage, can_assign_owner, can_manage_admins
from auth import errors, identity, session_store, signing
from auth import routes as auth_routes
from auth import emergency

logger = logging.getLogger("webapps")
logger.setLevel(logging.WARNING)
logger.addHandler(logging.StreamHandler())

# 不要求认证的路径前缀：登录本身必须可达，否则无法完成登录
_PUBLIC_PREFIXES = ("/auth/",)


def create_app():
    app = Flask(__name__, template_folder="templates")
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB max upload

    # embedded 形态下从 WSGI environ 删除所有客户端传入的 X-Auth-* 头。
    # 这是结构性防护：应用根本看不到这些头，不依赖每个读取点自觉忽略。
    app.wsgi_app = identity.StripAuthHeaders(
        app.wsgi_app, enabled=(config.AUTH_MODE != "gateway"))

    app.register_blueprint(auth_routes.bp)

    try:
        changelog.sync_prd_changelog()
    except Exception as e:
        logger.warning(f"PRD changelog sync failed on startup: {e}")

    try:
        stats = session_store.bootstrap()
        logger.warning(
            f"会话存储就绪：保留 {stats['sessions_kept']} 条，"
            f"清理过期 {stats['sessions_dropped']} 条")
    except Exception as e:
        logger.warning(f"会话存储初始化异常：{e}")

    # ── 请求级身份解析 ───────────────────────────────────────────────────────

    def _is_public_path(path: str) -> bool:
        return path.startswith(_PUBLIC_PREFIXES)

    @app.before_request
    def _resolve_identity():
        g.actor = None
        if _is_public_path(request.path):
            return None
        actor, error_status = identity.resolve_actor()
        if actor is None:
            if error_status == 403:
                return jsonify({
                    "success": False,
                    "message": "请求来源不被信任",
                }), 403
            if identity.wants_html():
                return redirect(
                    identity.login_url(request.full_path.rstrip("?")), code=302)
            return jsonify({
                "success": False,
                "message": "未登录或会话已过期，请重新登录",
                "needLogin": True,
            }), 401
        g.actor = actor
        return None

    def actor() -> permissions.Actor:
        return g.actor

    def get_client_ip():
        """
        取来源 IP。**仅用于审计展示**，不参与任何权限判定。

        这里仍然读 X-Forwarded-For：可信代理白名单的改造属于阶段一的独立事项，
        不在本 spec 范围内。由于 IP 已经不再决定权限，伪造它的收益只剩下污染
        审计日志的 ip 字段，危害等级远低于改造前。
        """
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.headers.get("X-Real-IP", request.remote_addr or "127.0.0.1")

    # ── 审计辅助 ─────────────────────────────────────────────────────────────

    def _project_title(key: str) -> str:
        meta = metadata.get_file_meta(key)
        if meta and meta.get("title"):
            return meta["title"]
        return key[5:] if key.startswith("file:") else key

    def audit_admin(action: str, target: str = "", detail: str = ""):
        a = actor()
        audit.log("admin", action, ip=get_client_ip(), target=target, detail=detail,
                  actor_id=(a.user_id if a else ""),
                  actor_name=(a.display if a else ""))

    def audit_project(action: str, key: str, detail: str = ""):
        a = actor()
        audit.log("project", action, ip=get_client_ip(),
                  target=_project_title(key), detail=detail,
                  actor_id=(a.user_id if a else ""),
                  actor_name=(a.display if a else ""))

    def audit_access(key: str, detail: str = ""):
        a = actor()
        audit.log("access", "查看项目", ip=get_client_ip(),
                  target=_project_title(key), detail=detail,
                  actor_id=(a.user_id if a else audit.ANONYMOUS_ACTOR_ID),
                  actor_name=(a.display if a else ""))

    def _project_key_for_path(filename: str):
        """只有项目入口才记访问日志，静态资源与子页面不记。"""
        if not filename or ".." in filename:
            return None
        parts = filename.split("/")
        if len(parts) == 1 and filename.lower().endswith(".html"):
            return f"file:{filename}"
        if len(parts) == 2 and parts[1].lower() == "index.html":
            return f"file:{filename}"
        return None

    def _deny(message: str, status: int = 403):
        return jsonify({"success": False, "message": message}), status

    # ── 当前用户与用户档案 ───────────────────────────────────────────────────

    @app.route("/api/me", methods=["GET"])
    def whoami():
        return jsonify({"success": True, "data": actor().to_public()})

    @app.route("/api/users", methods=["GET"])
    def list_users():
        """
        用户档案列表，供「指定负责人」「添加管理员」选人。

        走的是最小权限路线（没申请飞书通讯录读取），所以候选只能是登录过本系统
        的人 —— 这个限制在前端提示里要说清楚，否则超管会找不到想指定的同事。
        """
        return jsonify({"success": True, "data": user_directory.list_users()})

    # ── 项目列表 ─────────────────────────────────────────────────────────────

    @app.route("/api/files", methods=["GET"])
    def list_files():
        files = file_manager.scan_webapps()
        a = actor()
        preview_origin = config.PREVIEW_ORIGIN

        for f in files:
            meta = metadata.get_file_meta(f["key"]) or {}
            f["canManage"] = can_manage(meta, a)
            f["ownerName"] = user_directory.get_display_name(
                f.get("ownerId", ""), f.get("ownerName", "")) if f.get("ownerId") else ""
            # 预览域绝对 URL：主机名取自配置而不是请求 Host 头，防 Host 头注入
            if preview_origin:
                f["url"] = f"{preview_origin}{f['url']}"

        return jsonify({
            "success": True,
            "data": files,
            "baseUrl": preview_origin or f"http://{file_manager.get_local_ip()}:{PORT}",
        })

    # ── 上传 ─────────────────────────────────────────────────────────────────

    @app.route("/api/files/upload", methods=["POST"])
    def upload_file():
        """
        上传新项目。任意已认证用户都可以创建新项目（需求 7.11），
        新项目的负责人就是上传者。
        """
        a = actor()
        if not a.user_id or not a.display:
            return _deny("登录状态异常，请重新登录", 401)

        client_ip = get_client_ip()
        if "file" not in request.files:
            return _deny("没有上传文件", 400)
        file = request.files["file"]
        if file.filename == "":
            return _deny("文件名为空", 400)

        original_filename = file.filename
        original_lower = original_filename.lower()

        if original_lower.endswith(".zip"):
            zip_data = file.read()
            success, message, keys = file_manager.extract_zip(
                zip_data, client_ip, a.user_id, a.display)
            if success:
                for k in (keys or []):
                    audit_project("新建项目", k, detail=f"ZIP上传 {original_filename}")
                return jsonify({"success": True, "message": message, "keys": keys})
            return _deny(message, 400)

        if original_lower.endswith(".html"):
            import re
            safe_name = re.sub(r'[^\w\s\u4e00-\u9fff.\-()（）]', '', original_filename).strip()
            if not safe_name.lower().endswith(".html"):
                safe_name = safe_name + ".html"
            file_data = file.read()
            success, message, key = file_manager.upload_file(
                file_data, safe_name, client_ip, a.user_id, a.display)
            if success:
                audit_project("新建项目", key, detail=f"HTML上传 {safe_name}")
                return jsonify({"success": True, "message": message, "key": key})
            return _deny(message, 400)

        return _deny("只支持 HTML 或 ZIP 文件", 400)

    # ── 更新项目信息 / 密码 ──────────────────────────────────────────────────

    @app.route("/api/files/<path:key>", methods=["PUT"])
    def update_file(key):
        data = request.get_json(silent=True)
        if not data:
            return _deny("无效的请求数据", 400)

        title = data.get("title")
        description = data.get("description")
        product_line = data.get("productLine")
        password = data.get("password")
        if title is None and description is None and product_line is None and password is None:
            return _deny("没有提供要更新的字段", 400)

        existing = metadata.get_file_meta(key)
        if not existing:
            rel_path = key[5:] if key.startswith("file:") else ""
            if not rel_path or not (WEBAPPS_DIR / rel_path).exists():
                return _deny("文件不存在", 404)
            # 磁盘上有文件但没有元数据（手工放进去的历史遗留）：
            # 只有管理员能给它补建元数据，避免任何人抢先认领
            if not actor().is_admin:
                return _deny("无权编辑此项目", 403)
            metadata.set_file_meta(
                key=key, title=title or Path(rel_path).name, uploader_ip="",
                description=description or "", password=password,
                owner_id="", owner_name="")
        else:
            if not can_manage(existing, actor()):
                return _deny("无权编辑此项目", 403)
            metadata.update_file_meta(key, title, description, product_line, password)

        if password is not None:
            audit_project("设置密码" if password else "清除密码", key)
        else:
            audit_project("编辑信息", key)
        return jsonify({"success": True, "message": "已更新"})

    # ── 版本 ─────────────────────────────────────────────────────────────────

    @app.route("/api/files/<path:key>/versions", methods=["GET"])
    def get_versions(key):
        meta = metadata.get_file_meta(key)
        if not meta:
            return _deny("文件不存在", 404)
        return jsonify({"success": True, "data": metadata.get_versions(key)})

    @app.route("/api/files/<path:key>/versions", methods=["POST"])
    def upload_new_version(key):
        a = actor()
        client_ip = get_client_ip()
        filename = key[5:] if key.startswith("file:") else key

        meta = metadata.get_file_meta(key)
        has_physical = (WEBAPPS_DIR / filename).exists()
        if not meta and not has_physical:
            return _deny("文件不存在", 404)
        if not can_manage(meta, a):
            return _deny("无权更新此项目", 403)

        if "file" not in request.files:
            return _deny("没有上传文件", 400)
        upload = request.files["file"]
        if upload.filename == "":
            return _deny("文件名为空", 400)
        lower = upload.filename.lower()
        if not (lower.endswith(".zip") or lower.endswith(".html")):
            return _deny("只支持 HTML 或 ZIP 文件", 400)

        file_data = upload.read()
        if lower.endswith(".zip"):
            success, msg, _ = file_manager.extract_zip_for_version(
                file_data, filename, client_ip, a.user_id, a.display)
        else:
            success, msg, _ = file_manager.update_file_version(
                key, file_data, client_ip, a.user_id, a.display)

        if not success:
            return _deny(msg, 400)
        current_v = metadata.get_versions(key).get("current_version", "V1")
        audit_project("上传新版本", key,
                      detail=f"{'ZIP' if lower.endswith('.zip') else 'HTML'} -> {current_v}")
        return jsonify({"success": True, "message": msg, "version": current_v})

    @app.route("/api/files/<path:key>/versions/<version>/restore", methods=["PUT"])
    def restore_version(key, version):
        meta = metadata.get_file_meta(key)
        if not meta:
            return _deny("文件不存在", 404)
        if not can_manage(meta, actor()):
            return _deny("无权恢复此版本", 403)
        success, message = file_manager.restore_version_file(key, version, True)
        if success:
            audit_project("恢复版本", key, detail=f"-> {version}")
            return jsonify({"success": True, "message": message})
        return _deny(message, 400)

    @app.route("/api/files/<path:key>/versions/<version>", methods=["DELETE"])
    def delete_version(key, version):
        meta = metadata.get_file_meta(key)
        if not meta:
            return _deny("文件不存在", 404)
        if not can_manage(meta, actor()):
            return _deny("无权删除此版本", 403)
        success, message = file_manager.delete_version_file(key, version, True)
        if success:
            audit_project("删除版本", key, detail=f"{version}")
            return jsonify({"success": True, "message": message})
        return _deny(message, 400)

    @app.route("/api/files/<path:key>", methods=["DELETE"])
    def delete_file(key):
        meta = metadata.get_file_meta(key)
        allowed = can_manage(meta, actor())
        if meta and not allowed:
            return _deny("无权删除此项目", 403)
        if not meta and not actor().is_admin:
            # 无元数据的遗留文件只有管理员能清理
            return _deny("无权删除此项目", 403)
        # 先取标题再删，否则删完就查不到了
        title = _project_title(key)
        success, message = file_manager.delete_file(key, True)
        if success:
            a = actor()
            audit.log("project", "删除项目", ip=get_client_ip(), target=title,
                      actor_id=a.user_id, actor_name=a.display)
            return jsonify({"success": True, "message": message})
        status = 404 if "不存在" in message else 400
        return _deny(message, status)

    # ── 指定负责人（超管）───────────────────────────────────────────────────

    @app.route("/api/projects/owner", methods=["POST"])
    def assign_owner():
        """
        批量指定负责人。校验顺序固定为 权限(403) → 参数(400) → 项目存在性(404)，
        并且全有或全无 —— 任一项目标识不存在则整批不改动。
        """
        if not can_assign_owner(actor()):
            return _deny("只有超级管理员可以指定负责人", 403)

        data = request.get_json(silent=True) or {}
        raw_keys = data.get("keys")
        owner_id = (data.get("ownerId") or "").strip()
        if not isinstance(raw_keys, list) or not owner_id:
            return _deny("参数不完整", 400)

        keys = list(dict.fromkeys(k for k in raw_keys if isinstance(k, str) and k))
        if len(keys) == 0 or len(keys) > 100:
            return _deny("项目数量必须在 1~100 之间", 400)

        target = user_directory.get_user(owner_id)
        if not target:
            return _deny("该员工尚未登录过本系统，请让他先用飞书登录一次", 400)
        owner_name = target.get("name") or owner_id

        ok, missing, previous = metadata.set_owners_bulk(keys, owner_id, owner_name)
        if not ok:
            return _deny(f"项目不存在：{missing[0]}", 404)

        for key in keys:
            audit_project("指定负责人", key,
                          detail=f"{previous.get(key) or '（无）'} -> {owner_id}")
        return jsonify({"success": True,
                        "message": f"已为 {len(keys)} 个项目指定负责人",
                        "ownerName": owner_name})

    # ── 管理员名单 ───────────────────────────────────────────────────────────

    @app.route("/api/admins", methods=["GET"])
    def admin_list():
        return jsonify({"success": True, "data": user_directory.list_admins()})

    @app.route("/api/admins", methods=["POST"])
    def admin_add():
        if not can_manage_admins(actor()):
            return _deny("只有超级管理员可以维护管理员名单", 403)
        data = request.get_json(silent=True) or {}
        user_id = (data.get("userId") or "").strip()
        if not user_id:
            return _deny("缺少用户标识", 400)
        ok, message = user_directory.add_admin(user_id)
        if not ok:
            return _deny(message, 400)
        audit_admin("添加管理员", target=user_id, detail="普通管理员")
        return jsonify({"success": True, "message": message})

    @app.route("/api/admins/<user_id>", methods=["DELETE"])
    def admin_remove(user_id):
        if not can_manage_admins(actor()):
            return _deny("只有超级管理员可以维护管理员名单", 403)
        ok, message, status = user_directory.remove_admin(user_id, actor().user_id)
        if not ok:
            return _deny(message, status)
        audit_admin("删除管理员", target=user_id)
        return jsonify({"success": True, "message": message})

    # ── 系统信息 ─────────────────────────────────────────────────────────────

    @app.route("/api/status", methods=["GET"])
    def status():
        return jsonify({
            "success": True,
            "status": "running",
            "ip": file_manager.get_local_ip(),
            "port": PORT,
            "webappsDir": str(WEBAPPS_DIR),
            "version": changelog.get_latest_version(),
            "authMode": config.AUTH_MODE,
        })

    @app.route("/api/changelog", methods=["GET"])
    def get_changelog():
        return jsonify({
            "success": True,
            "data": changelog.get_changelog_entries(),
            "current_version": VERSION,
        })

    # ── 项目访问密码与访问凭证 ──────────────────────────────────────────────

    ACCESS_COOKIE = "wl_access"

    def _access_cookie_name(key: str) -> str:
        import hashlib
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        return f"{ACCESS_COOKIE}_{digest}"

    @app.route("/api/files/<path:key>/session", methods=["GET"])
    def check_file_session(key):
        meta = metadata.get_file_meta(key)
        has_password = bool(meta and meta.get("password"))
        if not has_password:
            return jsonify({"success": True, "hasAccess": True, "hasPassword": False})
        token = request.cookies.get(_access_cookie_name(key), "")
        valid = signing.verify_access_credential(
            token, actor().user_id, key, meta.get("password"))
        return jsonify({"success": True, "hasAccess": valid, "hasPassword": True})

    @app.route("/api/files/<path:key>/password", methods=["POST"])
    def check_password(key):
        """
        校验项目访问密码，通过则签发无状态访问凭证。

        凭证绑定 用户 + 项目 + 密码版本，8 小时有效；密码一改，旧凭证在下次
        校验时自动失效（密码版本对不上），不需要维护撤销列表。
        """
        a = actor()
        data = request.get_json(silent=True) or {}
        password = data.get("password", "")
        if len(str(password)) > 128:
            return _deny("密码过长", 400)

        blocked, remain = session_store.emergency_is_blocked(f"pwd:{a.user_id}:{key}")
        if blocked:
            return jsonify({"success": False,
                            "message": f"尝试过于频繁，请 {remain // 60 + 1} 分钟后再试"}), 429

        meta = metadata.get_file_meta(key)
        if not metadata.check_file_password(key, password):
            session_store.emergency_record_failure(f"pwd:{a.user_id}:{key}")
            audit_project("密码校验失败", key)
            return _deny("密码错误", 401)

        session_store.emergency_clear_failures(f"pwd:{a.user_id}:{key}")
        credential = signing.issue_access_credential(
            a.user_id, key, (meta or {}).get("password"))
        resp = jsonify({"success": True, "message": "密码正确"})
        resp.set_cookie(
            _access_cookie_name(key), credential,
            max_age=config.ACCESS_CREDENTIAL_TTL, httponly=True,
            secure=config.IS_PRODUCTION, samesite="Lax", path="/",
            domain=identity.cookie_domain_for_request(),
        )
        return resp

    # ── 审计日志 ─────────────────────────────────────────────────────────────

    @app.route("/api/logs", methods=["GET"])
    def get_logs():
        """任意已登录管理员均可查看全部日志；普通员工不可见。"""
        if not actor().is_admin:
            return _deny("需要管理员权限", 403)
        try:
            page = int(request.args.get("page", 1))
        except ValueError:
            page = 1
        try:
            page_size = int(request.args.get("pageSize", 100))
        except ValueError:
            page_size = 100
        try:
            result = audit.query(
                q=request.args.get("q", ""),
                actor=request.args.get("actor", ""),
                actor_id=request.args.get("actor_id", ""),
                ip=request.args.get("ip", ""),
                category=request.args.get("category", ""),
                action_type=request.args.get("action_type", ""),
                page=page, page_size=page_size)
            return jsonify({"success": True, **result})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    # ── 原型内容服务 ─────────────────────────────────────────────────────────

    def _sandbox_headers():
        """
        embedded 形态的缓解措施：给原型内容加 sandbox CSP，使它进入独立的
        不透明源，读不到管理界面的 Cookie 与 localStorage。

        代价是依赖 localStorage 或同源 fetch 的原型会失效，因此可通过
        PREVIEW_SANDBOX 关闭 —— 但关掉就等于恢复到接入 SSO 之前的风险水平。
        gateway 形态用域名隔离，不需要这个。
        """
        if config.AUTH_MODE == "gateway" or not config.PREVIEW_SANDBOX:
            return {"X-Content-Type-Options": "nosniff"}
        return {
            "Content-Security-Policy": "sandbox allow-scripts allow-forms allow-popups",
            "X-Content-Type-Options": "nosniff",
        }

    def _serve_project_file(filename: str):
        response = send_from_directory(WEBAPPS_DIR, filename)
        for k, v in _sandbox_headers().items():
            response.headers[k] = v
        return response

    @app.route("/files/<path:filename>")
    def serve_file(filename):
        pkey = _project_key_for_path(filename)
        if pkey:
            meta = metadata.get_file_meta(pkey)
            if meta and meta.get("password"):
                return redirect(f"/protected/{filename}", code=302)
            audit_access(pkey)
        return _serve_project_file(filename)

    @app.route("/protected/<path:filename>")
    def serve_protected_file(filename):
        key = f"file:{filename}"
        meta = metadata.get_file_meta(key)
        if not meta or not meta.get("password"):
            pkey = _project_key_for_path(filename)
            if pkey:
                audit_access(pkey)
            return _serve_project_file(filename)

        token = request.cookies.get(_access_cookie_name(key), "")
        if signing.verify_access_credential(
                token, actor().user_id, key, meta.get("password")):
            audit_access(key)
            return _serve_project_file(filename)
        return _password_prompt_page(key, filename)

    def _password_prompt_page(key: str, filename: str):
        import html as _html
        safe_key = _html.escape(key, quote=True)
        return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>需要密码访问</title>
<style>
 body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        display:flex;justify-content:center;align-items:center;min-height:100vh;
        margin:0;background:#f1f3f4;color:#202124; }}
 .card {{ background:#fff;padding:36px 40px;border-radius:12px;max-width:400px;
         width:90%;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.12); }}
 h2 {{ font-size:18px;margin:0 0 8px; }}
 p {{ color:#5f6368;font-size:14px;margin:0 0 20px; }}
 input {{ width:100%;padding:11px;border:1px solid #dadce0;border-radius:6px;
         box-sizing:border-box;font-size:14px; }}
 button {{ width:100%;padding:11px;margin-top:12px;background:#4285f4;color:#fff;
          border:none;border-radius:6px;font-size:15px;cursor:pointer; }}
 .err {{ color:#ea4335;font-size:13px;margin-top:10px;display:none; }}
 @media (prefers-color-scheme: dark) {{
   body {{ background:#202124;color:#e8eaed; }}
   .card {{ background:#292a2d;box-shadow:none; }}
   input {{ background:#202124;border-color:#5f6368;color:#e8eaed; }}
 }}
</style></head><body>
<div class="card">
  <h2>🔒 此项目已加密</h2>
  <p>请输入访问密码</p>
  <form id="f"><input type="password" id="p" placeholder="访问密码" required>
  <button type="submit">确认访问</button></form>
  <p class="err" id="e">密码错误</p>
</div>
<script>
document.getElementById('f').onsubmit = async function(ev) {{
  ev.preventDefault();
  try {{
    const r = await fetch('/api/files/' + encodeURIComponent('{safe_key}') + '/password', {{
      method:'POST', credentials:'same-origin',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{password: document.getElementById('p').value}})
    }});
    const d = await r.json();
    if (d.success) {{ window.location.reload(); }}
    else {{ const e=document.getElementById('e'); e.textContent=d.message||'密码错误'; e.style.display='block'; }}
  }} catch(_) {{ document.getElementById('e').style.display='block'; }}
}};
</script></body></html>""", 401

    @app.route("/assets/<path:filename>")
    def serve_assets(filename):
        return send_from_directory(Path(__file__).parent / "templates" / "assets",
                                   filename)

    def _inject_base_href(content: bytes, filename: str, version: str) -> bytes:
        import re as _re
        from urllib.parse import quote
        safe_filename = quote(filename, safe="/")
        base_tag = f'<base href="/versions/{safe_filename}/{version}/res/">'.encode()
        match = _re.search(rb'<head[^>]*>', content, _re.IGNORECASE)
        if match:
            return content[:match.end()] + base_tag + content[match.end():]
        return base_tag + content

    @app.route("/versions/<path:filename>/<version>")
    def serve_version(filename, version):
        key = f"file:{filename}"
        meta = metadata.get_file_meta(key)
        if meta and meta.get("password"):
            token = request.cookies.get(_access_cookie_name(key), "")
            if not signing.verify_access_credential(
                    token, actor().user_id, key, meta.get("password")):
                return _password_prompt_page(key, filename)

        content = file_manager.get_version_content(filename, version)
        headers = {"Content-Type": "text/html; charset=utf-8", **_sandbox_headers()}
        if content is not None:
            audit_access(key, detail=f"历史版本 {version}")
            return _inject_base_href(content, filename, version), 200, headers
        content = file_manager.get_current_content(filename)
        if content is not None:
            audit_access(key, detail=f"请求{version}，返回当前版本")
            return content, 200, headers
        return "文件不存在", 404

    @app.route("/versions/<path:filename>/<version>/res/<path:subpath>")
    def serve_version_subresource(filename, version, subpath):
        content = file_manager.get_version_subresource(filename, version, subpath)
        if content is None:
            return "资源不存在", 404
        import mimetypes
        mime_type = mimetypes.guess_type(subpath)[0] or "application/octet-stream"
        return content, 200, {"Content-Type": mime_type, **_sandbox_headers()}

    # ── SPA ──────────────────────────────────────────────────────────────────

    @app.route("/", methods=["GET"])
    def index():
        return send_file(Path(__file__).parent / "templates" / "index.html")

    return app


def main():
    # 认证配置有误时在这里终止，不监听任何端口
    config.abort_on_invalid_auth_config()

    app = create_app()
    local_ip = file_manager.get_local_ip()
    print("=" * 56)
    print("WebApps Link Manager 已启动")
    print("=" * 56)
    print(f"管理界面   : http://{local_ip}:{PORT}/")
    print(f"文件目录   : {WEBAPPS_DIR}")
    print(f"身份模式   : {config.AUTH_MODE}")
    print(f"部署环境   : {config.DEPLOY_ENV}")
    admins = user_directory.admin_count()
    print(f"管理员数量 : {admins}" + ("（首个通过飞书应用管理员校验的登录者将成为超管）"
                                     if admins == 0 else ""))
    if config.EMERGENCY_ENABLED:
        host, port = config.emergency_host_port()
        print(f"应急通道   : http://{host}:{port}/emergency/login （仅本机可访问）")
    print("=" * 56)

    if config.EMERGENCY_ENABLED:
        emergency.start_in_background()

    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
