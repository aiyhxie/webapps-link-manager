"""
统一错误页。

三条约束（需求 13.6、12.5）：
- 不回显飞书返回的原始响应内容，只给分类说明
- 不暴露应急管理员通道的路径
- 不出现 App Secret、access_token、授权码、会话标识
"""
import html
from typing import Optional, Tuple

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         display: flex; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; background: #f1f3f4; color: #202124; }}
  .card {{ background: #fff; padding: 36px 40px; border-radius: 12px; max-width: 460px;
          width: 90%; box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
  h1 {{ font-size: 18px; margin: 0 0 12px; }}
  p {{ font-size: 14px; line-height: 1.7; color: #5f6368; margin: 0 0 20px; }}
  .code {{ font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #9aa0a6; }}
  a.btn {{ display: inline-block; background: #4285f4; color: #fff; text-decoration: none;
          padding: 10px 20px; border-radius: 6px; font-size: 14px; }}
  a.btn:hover {{ background: #3367d6; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #202124; color: #e8eaed; }}
    .card {{ background: #292a2d; box-shadow: none; }}
    p {{ color: #9aa0a6; }}
  }}
</style>
</head>
<body>
  <div class="card">
    <h1>{title}</h1>
    <p>{detail}</p>
    {action}
    {code}
  </div>
</body>
</html>
"""


def error_page(title: str, detail: str, action_label: str = "",
               action_href: str = "", code: str = "",
               status: int = 400) -> Tuple[str, int, dict]:
    """
    渲染一个错误页。

    code 只放飞书的业务错误码这类**非敏感**标识，用于对着日志排查；
    绝不放响应体原文。
    """
    action_html = ""
    if action_label and action_href:
        action_html = (f'<a class="btn" href="{html.escape(action_href, quote=True)}">'
                       f'{html.escape(action_label)}</a>')
    code_html = f'<p class="code">错误标识：{html.escape(str(code))}</p>' if code else ""
    body = _PAGE.format(
        title=html.escape(title),
        detail=html.escape(detail),
        action=action_html,
        code=code_html,
    )
    return body, status, {"Content-Type": "text/html; charset=utf-8"}


def login_required_page(login_url: str = "/auth/login") -> Tuple[str, int, dict]:
    return error_page(
        "需要登录", "请使用飞书扫码登录后继续访问。",
        "去登录", login_url, status=401,
    )


def auth_failed_page(reason: str, feishu_code: Optional[object] = None,
                     retry_url: str = "/auth/login") -> Tuple[str, int, dict]:
    return error_page(
        "登录失败", reason, "重新发起授权", retry_url,
        code=feishu_code if feishu_code is not None else "", status=400,
    )


def feishu_unavailable_page(retry_url: str = "/auth/login") -> Tuple[str, int, dict]:
    return error_page(
        "飞书暂时无法访问",
        "与飞书开放平台的通信超时或失败，本次登录未完成。"
        "已登录的会话不受影响，稍后重试即可。",
        "重新发起授权", retry_url, status=503,
    )
