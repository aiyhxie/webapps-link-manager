"""
应急管理员通道。

为什么需要它：SSO 上线后登录完全依赖飞书。飞书接口故障、应用被误停用、权限被
管理员撤销、或自己被移出可用范围时，**所有人都进不去系统**，连恢复都得直接登
服务器改文件。这个通道就是那种时候的兜底入口。

它本身是攻击面，因此约束比主入口更严：
- 独占一个只绑回环地址的套接字。靠 remote_addr 判断不够 —— 需求要求「非本机
  连接无法建立」，那就必须是独立 socket。
- 启动前校验绑定地址，不是回环就**拒绝启动整个进程**。配置写错不可能上线。
- 请求进来再查一次 remote_addr，双保险。
- 会话固定 60 分钟，不因活动续期。
- 密码 16~128 字符且四类字符至少三类，bcrypt 存储。
- 15 分钟滑动窗口 5 次失败 → 封禁 15 分钟，凭据正确也拒绝。

它复用主应用的会话存储，签发 kind=emergency 的会话，因此登录后在主端口上也
是有效身份（需求 9.9：会话有效期内拥有超级管理员权限）。
"""
import logging
import sys
import threading
from pathlib import Path
from typing import Optional, Tuple

from flask import Flask, jsonify, make_response, request

_server_dir = Path(__file__).parent.parent.resolve()
if str(_server_dir) not in sys.path:
    sys.path.insert(0, str(_server_dir))

import audit
import config
import metadata
from auth import identity, session_store

logger = logging.getLogger("webapps.auth.emergency")

ACCOUNT_PREFIX = "emergency:"
FAILURE_WINDOW = 900          # 15 分钟
FAILURE_THRESHOLD = 5
PASSWORD_MIN = 16
PASSWORD_MAX = 128


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """16~128 字符，且大写/小写/数字/符号四类里至少三类。"""
    if not password or not (PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        return False, f"密码长度必须在 {PASSWORD_MIN}~{PASSWORD_MAX} 字符之间"
    classes = 0
    if any(c.isupper() for c in password):
        classes += 1
    if any(c.islower() for c in password):
        classes += 1
    if any(c.isdigit() for c in password):
        classes += 1
    if any(not c.isalnum() for c in password):
        classes += 1
    if classes < 3:
        return False, "密码需包含大写字母、小写字母、数字、符号中的至少三类"
    return True, ""


def _is_loopback_peer() -> bool:
    peer = (request.remote_addr or "").strip()
    return peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def _audit(action: str, account: str, detail: str) -> None:
    try:
        audit.log("admin", action, ip=(request.remote_addr or ""),
                  target=account, detail=detail,
                  actor_id=f"{ACCOUNT_PREFIX}{account}" if account else "",
                  actor_name=account or "")
    except Exception:
        pass


def create_emergency_app() -> Flask:
    app = Flask(__name__)

    @app.before_request
    def _guard_loopback():
        """
        双保险：即使套接字被错误地绑到了对外地址，非本机来源也一律拒绝，
        而且在校验任何凭据之前就拒绝（需求 9.2）。
        """
        if not _is_loopback_peer():
            _audit("应急通道拒绝访问", "", f"来源地址非回环：{request.remote_addr}")
            return jsonify({"success": False,
                            "message": "应急通道仅允许从服务器本机访问"}), 403
        return None

    @app.route("/emergency/login", methods=["GET"])
    def login_page():
        return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>应急管理员登录</title>
<style>
 body{font-family:-apple-system,sans-serif;display:flex;align-items:center;
      justify-content:center;min-height:100vh;margin:0;background:#1e1e1e;color:#d4d4d4}
 .card{background:#292a2d;padding:32px 36px;border-radius:12px;width:90%;max-width:400px}
 h2{font-size:17px;margin:0 0 6px}
 p{font-size:13px;color:#9aa0a6;margin:0 0 18px;line-height:1.6}
 input{width:100%;padding:10px;margin:6px 0;border:1px solid #5f6368;border-radius:6px;
       background:#202124;color:#e8eaed;box-sizing:border-box}
 button{width:100%;padding:11px;margin-top:10px;background:#8ab4f8;color:#202124;
        border:none;border-radius:6px;font-size:15px;cursor:pointer;font-weight:600}
 .msg{font-size:13px;margin-top:12px;display:none}
 .err{color:#f28b82}.ok{color:#81c995}
</style></head><body>
<div class="card">
 <h2>应急管理员登录</h2>
 <p>仅在飞书登录不可用时使用。本入口只接受来自服务器本机的访问，
    登录后获得 60 分钟超级管理员权限，且不会自动延长。</p>
 <form id="f">
  <input id="u" placeholder="账号" autocomplete="off" required>
  <input id="p" type="password" placeholder="密码" required>
  <button type="submit">登录</button>
 </form>
 <div class="msg err" id="e"></div>
 <div class="msg ok" id="s"></div>
</div>
<script>
document.getElementById('f').onsubmit = async function(ev){
  ev.preventDefault();
  const e=document.getElementById('e'), s=document.getElementById('s');
  e.style.display='none'; s.style.display='none';
  const r = await fetch('/emergency/login', {method:'POST',
    headers:{'Content-Type':'application/json'}, credentials:'same-origin',
    body: JSON.stringify({username:document.getElementById('u').value,
                          password:document.getElementById('p').value})});
  const d = await r.json();
  if (d.success) { s.textContent = d.message + '（会话已建立，可回主端口使用）';
                   s.style.display='block'; }
  else { e.textContent = d.message || '登录失败'; e.style.display='block'; }
};
</script></body></html>"""

    @app.route("/emergency/login", methods=["POST"])
    def login():
        data = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        if not username or not password:
            return jsonify({"success": False, "message": "请输入账号和密码"}), 400

        blocked, remain = session_store.emergency_is_blocked(username)
        if blocked:
            _audit("应急登录失败", username, "处于限流封禁中")
            return jsonify({
                "success": False,
                "message": f"失败次数过多，请 {remain // 60 + 1} 分钟后再试",
            }), 429

        if not metadata.verify_admin_password(username, password):
            session_store.emergency_record_failure(
                username, window=FAILURE_WINDOW, threshold=FAILURE_THRESHOLD)
            _audit("应急登录失败", username, "账号或密码错误")
            return jsonify({"success": False, "message": "账号或密码错误"}), 401

        session_store.emergency_clear_failures(username)
        session_id = session_store.create_session(
            user_id=f"{ACCOUNT_PREFIX}{username}",
            name=f"{username}（应急）",
            domain=session_store.DOMAIN_ADMIN,
            kind=session_store.KIND_EMERGENCY,
            ttl=config.EMERGENCY_SESSION_TTL,
        )
        _audit("应急登录成功", username,
               f"有效期 {config.EMERGENCY_SESSION_TTL // 60} 分钟，不续期")

        response = make_response(jsonify({
            "success": True,
            "message": f"登录成功，{config.EMERGENCY_SESSION_TTL // 60} 分钟内有效",
        }))
        # Cookie 不设 domain，让浏览器按 host-only 处理；本机访问主端口时同样携带
        response.set_cookie(
            identity.COOKIE_ADMIN, session_id, httponly=True, secure=False,
            samesite="Lax", path="/", max_age=config.EMERGENCY_SESSION_TTL)
        return response

    return app


_thread: Optional[threading.Thread] = None


def start_in_background() -> None:
    """
    在后台线程启动应急通道。

    多 worker 部署时每个 worker 都会各起一份而争抢端口，因此改用 gunicorn 后
    需要改成仅主 worker 启动或独立进程运行 —— 已在任务 18 与部署说明中记录。
    这里对端口占用做了容错，重复启动不会让主服务崩掉。
    """
    global _thread
    if _thread is not None:
        return
    host, port = config.emergency_host_port()
    if not config.is_loopback_host(host):
        # 正常不会走到：config.abort_on_invalid_auth_config() 已在启动阶段拦住
        raise config.ConfigError(f"应急通道监听地址必须是回环地址，当前为 {host}")

    app = create_emergency_app()

    def _run():
        try:
            app.run(host=host, port=port, debug=False, threaded=True,
                    use_reloader=False)
        except OSError as e:
            logger.warning(f"应急通道启动失败（端口可能已被占用）：{e}")

    _thread = threading.Thread(target=_run, name="emergency-channel", daemon=True)
    _thread.start()
