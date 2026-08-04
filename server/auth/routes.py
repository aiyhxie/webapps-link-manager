"""
认证路由（Blueprint）。

/auth/login            未登录则 302 到飞书授权页；已登录直接回跳
/auth/feishu/callback  校验 state → 换令牌 → 取用户信息 → 建档 → 签发会话 → 回跳
/auth/logout           删除当前域会话并使 Cookie 立即失效
/auth/verify           gateway 形态的 auth_request 校验端点
/auth/handoff          管理域签发一次性跳转凭证，302 到预览域
/auth/preview-entry    预览域消费跳转凭证，签发预览域独立会话
/auth/health           健康检查，排除在认证要求之外

这些路径全部不要求已认证（否则登录本身无法进行），由 app.py 的
before_request 白名单放行。
"""
import logging
import sys
import urllib.parse
from pathlib import Path
from typing import Optional

from flask import Blueprint, jsonify, make_response, redirect, request

_server_dir = Path(__file__).parent.parent.resolve()
if str(_server_dir) not in sys.path:
    sys.path.insert(0, str(_server_dir))

import audit
import config
import user_directory
from auth import errors, feishu, identity, session_store, signing

logger = logging.getLogger("webapps.auth.routes")

bp = Blueprint("auth", __name__, url_prefix="/auth")


# ── 工具 ─────────────────────────────────────────────────────────────────────

def _pick_redirect_uri() -> Optional[str]:
    """
    选出本次授权使用的回调地址。

    只能取自当前部署环境的允许列表，且优先选主机名与当前请求一致的那个 ——
    否则飞书回调会打到另一个地址，会话 Cookie 就写不到用户当前访问的域上。
    """
    allowed = config.allowed_callback_urls()
    if not allowed:
        return None
    host = (request.host or "").lower()
    for url in allowed:
        if urllib.parse.urlsplit(url).netloc.lower() == host:
            return url
    return allowed[0]


def _safe_return_to(raw: str) -> str:
    """
    回跳目标白名单（需求 1.9 / 1.10）。

    只接受以单个 / 开头的站内相对路径，或主机名等于管理域/预览域的绝对地址。
    `//evil.com` 这种「协议相对 URL」会被浏览器当成跨站跳转，必须挡掉，
    所以判断的是「以 / 开头且第二个字符不是 /」。
    """
    if not raw:
        return "/"
    if raw.startswith("/") and not raw.startswith("//"):
        return raw
    parsed = urllib.parse.urlsplit(raw)
    allowed_hosts = {
        identity._host_of(config.ADMIN_ORIGIN),
        identity._host_of(config.PREVIEW_ORIGIN),
    } - {""}
    if parsed.netloc.lower() in allowed_hosts:
        return raw
    return "/"


def _set_session_cookie(response, session_id: str, domain: str):
    response.set_cookie(
        identity.cookie_name_for(domain),
        session_id,
        httponly=True,
        secure=config.IS_PRODUCTION,   # 开发期回调是 http，加 Secure 会写不进去
        samesite="Lax",
        path="/",
        domain=identity.cookie_domain_for_request(),
        max_age=config.SESSION_ABSOLUTE_MAX,
    )
    return response


def _clear_session_cookie(response, domain: str):
    response.set_cookie(
        identity.cookie_name_for(domain), "",
        expires=0, httponly=True, secure=config.IS_PRODUCTION,
        samesite="Lax", path="/", domain=identity.cookie_domain_for_request(),
    )
    return response


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.headers.get("X-Real-IP", request.remote_addr or "")


def _audit_auth(action: str, actor: str, detail: str = "", target: str = "") -> None:
    """写一条认证相关审计。绝不带 Secret / token / 授权码。"""
    try:
        audit.log("admin", action, actor=actor or "-", ip=_client_ip(),
                  target=target, detail=detail,
                  actor_id=actor or "", actor_name=actor or "")
    except Exception:
        pass          # 审计失败不能影响认证流程


# ── 登录 ─────────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET"])
def login():
    domain = identity.current_domain()
    return_to = _safe_return_to(request.args.get("return_to", ""))

    # 已登录则跳过授权流程，直接回跳（需求 1.15）
    actor, _sid = identity.resolve_session_actor(domain)
    if actor:
        return redirect(return_to, code=302)

    redirect_uri = _pick_redirect_uri()
    if not redirect_uri:
        return errors.error_page(
            "登录未就绪",
            "当前部署环境没有可用的飞书回调地址，请检查 ADMIN_ORIGIN 配置。",
            status=500,
        )

    state = session_store.create_state(return_to, redirect_uri)
    return redirect(feishu.authorize_url(redirect_uri, state), code=302)


@bp.route("/feishu/callback", methods=["GET"])
def feishu_callback():
    code = (request.args.get("code") or "").strip()
    state = (request.args.get("state") or "").strip()

    # state 的四种失败（缺失 / 无记录 / 已过期 / 已使用）统一按 400 处理，
    # 不区分原因，避免把内部状态泄露给调用方（需求 1.4）
    state_record = session_store.consume_state(state)
    if state_record is None:
        _audit_auth("登录失败", "-", detail="state 校验未通过")
        return errors.auth_failed_page("登录请求已失效，请重新发起。")

    if not code:
        _audit_auth("登录失败", "-", detail="回调缺少授权码")
        return errors.auth_failed_page("回调缺少授权码，请重新发起登录。")

    redirect_uri = state_record.get("redirect_uri") or _pick_redirect_uri()
    if redirect_uri not in config.allowed_callback_urls():
        _audit_auth("登录失败", "-", detail="回调地址不在允许列表内")
        return errors.auth_failed_page("回调地址不被允许。")

    try:
        user_token = feishu.exchange_user_token(code, redirect_uri)
        info = feishu.get_user_info(user_token)
    except feishu.FeishuUnavailable as e:
        _audit_auth("登录失败", "-", detail=f"飞书不可用 环节={e.stage}")
        return errors.feishu_unavailable_page()
    except feishu.FeishuError as e:
        _audit_auth("登录失败", "-",
                    detail=f"飞书返回错误 环节={e.stage} code={e.code}")
        if e.stage == "exchange_token":
            return errors.error_page(
                "登录失败", "授权码无效或已被使用，请重新登录。",
                "重新登录", "/auth/login", code=e.code, status=400)
        return errors.auth_failed_page("获取用户信息失败，请重试。", e.code)

    user_id = info["user_id"]
    name = info["name"]
    user_directory.upsert_user(user_id, name)

    # 首个超级管理员 bootstrap：仅在名单为空时尝试一次
    if user_directory.admin_count() == 0:
        try:
            if feishu.is_app_admin(user_id):
                if user_directory.bootstrap_super_admin(user_id, name):
                    _audit_auth("授予超级管理员", name, target=user_id,
                                detail="首次登录且为飞书应用管理员")
            else:
                _audit_auth("跳过超管授予", name, target=user_id,
                            detail="非飞书应用管理员")
        except feishu.FeishuError as e:
            # 接口失败不阻断登录，按普通员工处理并记审计（需求 8.4）
            _audit_auth("跳过超管授予", name, target=user_id,
                        detail=f"管理员校验失败 code={e.code}")

    domain = identity.current_domain()
    session_id = session_store.create_session(user_id, name, domain)
    _audit_auth("登录", name, target=user_id, detail="飞书扫码登录")

    return_to = _safe_return_to(state_record.get("return_to", "/"))
    response = make_response(redirect(return_to, code=302))
    return _set_session_cookie(response, session_id, domain)


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    """
    登出：只删当前域的会话，另一域不受影响；记录不存在时结果一致（幂等）。
    """
    domain = identity.current_domain()
    session_id = request.cookies.get(identity.cookie_name_for(domain), "")
    actor, _ = identity.resolve_session_actor(domain)
    session_store.delete_session(session_id)
    if actor:
        _audit_auth("退出登录", actor.display, target=actor.user_id)

    if identity.wants_html():
        response = make_response(redirect("/auth/login", code=302))
    else:
        response = make_response(jsonify({"success": True, "message": "已退出登录"}))
    return _clear_session_cookie(response, domain)


# ── gateway 形态：校验端点与跨域跳转 ─────────────────────────────────────────

@bp.route("/verify", methods=["GET"])
def verify():
    """
    Nginx auth_request 的校验端点。

    200 时把身份放在响应头里，由网关取出后作为请求头注入给业务应用；
    401 时网关按 Accept 决定是 302 到登录页还是直接回 401。
    """
    domain = identity.current_domain()
    actor, _sid = identity.resolve_session_actor(domain)
    if not actor:
        return "", 401
    response = make_response("", 200)
    response.headers[identity.HEADER_USER_ID] = actor.user_id
    response.headers[identity.HEADER_USER_NAME] = identity.encode_user_name(actor.display)
    return response


@bp.route("/handoff", methods=["GET"])
def handoff():
    """
    管理域签发一次性跳转凭证，把用户送到预览域并在那里建立独立会话。

    管理域没有有效会话时先走飞书授权（由 /auth/login 处理），
    授权完成后会回到这里。
    """
    to = request.args.get("to", "/")
    actor, _sid = identity.resolve_session_actor(session_store.DOMAIN_ADMIN)
    if not actor:
        return redirect(identity.login_url(f"/auth/handoff?to={urllib.parse.quote(to, safe='')}"),
                        code=302)
    jti = session_store.register_handoff(actor.user_id)
    credential = signing.issue_handoff_credential(actor.user_id, jti)
    preview = config.PREVIEW_ORIGIN or ""
    target = (f"{preview}/auth/preview-entry"
              f"?c={urllib.parse.quote(credential, safe='')}"
              f"&to={urllib.parse.quote(to, safe='')}")
    return redirect(target, code=302)


@bp.route("/preview-entry", methods=["GET"])
def preview_entry():
    """预览域消费跳转凭证：校验签名、未过期、未使用，随后签发预览域会话。"""
    credential = request.args.get("c", "")
    to = _safe_return_to(request.args.get("to", "/"))

    payload = signing.verify(credential, "handoff")
    if not payload:
        return redirect(f"{config.ADMIN_ORIGIN}/auth/login", code=302)
    user_id = payload.get("sub", "")
    jti = payload.get("jti", "")
    if not session_store.consume_handoff(jti, user_id):
        return redirect(f"{config.ADMIN_ORIGIN}/auth/login", code=302)

    name = user_directory.get_display_name(user_id)
    session_id = session_store.create_session(
        user_id, name, session_store.DOMAIN_PREVIEW)
    response = make_response(redirect(to, code=302))
    return _set_session_cookie(response, session_id, session_store.DOMAIN_PREVIEW)


@bp.route("/health", methods=["GET"])
def health():
    """健康检查。刻意不暴露版本、路径、配置等内部信息。"""
    return jsonify({"status": "ok"})
