#!/usr/bin/env python3
"""
安全回归脚本（可重复执行）。

用法：
    python3 server/tests/security_regression.py [--base http://localhost:8080]

覆盖的是「一旦回归就会造成越权」的那几条，全部是只读或注定失败的请求，
不会修改任何数据：

1. Property 1  伪造 X-Auth-* 身份头必须无效（含大小写与下划线变体）
2. Property 1  伪造身份头 + 写操作必须被拒且不改数据
3. 需求 2.15   X-Admin-Token 携带任意值的结果与不携带完全一致
4. 需求 9.1/9.3 应急通道只在回环地址监听，不对外可达
5. 需求 2.2    /auth/* 与健康检查免认证，其余路径一律要求认证
6. 需求 2.4    HTML 请求 302 到登录入口，非 HTML 请求 401 且响应体无受保护内容

这个脚本的价值在于：改造前的 get_client_ip() 无条件信任 X-Forwarded-For 就是
同一类问题（信任客户端可控的输入），把这类断言固化成脚本，避免重犯。
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from typing import Optional, Tuple

TIMEOUT = 6
_ctx = ssl.create_default_context()

PASS = "PASS"
FAIL = "FAIL"

_results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    mark = f"  {PASS}  " if ok else f"  {FAIL}  "
    print(f"{mark}{name}" + (f"    ({detail})" if detail else ""))


def fetch(url: str, method: str = "GET", headers: Optional[dict] = None,
          body: Optional[bytes] = None) -> Tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def fetch_no_redirect(url: str, headers: Optional[dict] = None) -> Tuple[int, str]:
    """不跟随重定向，用于检查 302 目标。"""
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            return r.status, r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "") if e.headers else ""
    except Exception as e:
        return -1, f"{type(e).__name__}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8080")
    parser.add_argument("--emergency-port", type=int, default=8099)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    print("=" * 64)
    print(f"安全回归：{base}")
    print("=" * 64)

    # 基线：未认证访问受保护接口
    print("\n[1] 认证边界")
    status, _ = fetch(f"{base}/api/files")
    record("未认证访问 /api/files 返回 401", status == 401, f"HTTP {status}")

    status, _ = fetch(f"{base}/auth/health")
    record("/auth/health 免认证可达", status == 200, f"HTTP {status}")

    status, location = fetch_no_redirect(f"{base}/auth/login")
    record("/auth/login 302 到飞书授权页",
           status == 302 and "open.feishu.cn" in (location or ""),
           f"HTTP {status}")

    status, location = fetch_no_redirect(base + "/", {"Accept": "text/html"})
    record("HTML 请求未认证时 302 到登录入口",
           status == 302 and "/auth/login" in (location or ""),
           f"HTTP {status} → {location}")

    status, body = fetch(f"{base}/api/files", headers={"Accept": "application/json"})
    no_leak = "webapps" not in body.lower() and '"data"' not in body
    record("非 HTML 请求 401 且响应体不含受保护内容",
           status == 401 and no_leak, f"HTTP {status}")

    # Property 1：伪造身份头
    print("\n[2] Property 1 · 伪造身份头必须无效")
    for header in ("X-Auth-User-Id", "x-auth-user-id", "X_Auth_User_Id",
                   "X-AUTH-USER-ID", "X-Auth-User-Name"):
        status, _ = fetch(f"{base}/api/files", headers={header: "ou_forged"})
        record(f"读接口忽略伪造头 {header}", status == 401, f"HTTP {status}")

    status, _ = fetch(f"{base}/api/me",
                      headers={"X-Auth-User-Id": "ou_forged",
                               "X-Auth-User-Name": "%E9%AD%94"})
    record("伪造头无法冒充身份访问 /api/me", status == 401, f"HTTP {status}")

    print("\n[3] Property 1 · 伪造身份头 + 写操作")
    payload = json.dumps({"title": "SECURITY_REGRESSION_SHOULD_NOT_APPLY"}).encode()
    status, _ = fetch(f"{base}/api/files/file%3Aindex.html", method="PUT",
                      headers={"X-Auth-User-Id": "ou_forged",
                               "Content-Type": "application/json"},
                      body=payload)
    record("伪造头的 PUT 被拒", status in (401, 403), f"HTTP {status}")

    status, _ = fetch(f"{base}/api/files/file%3Aindex.html", method="DELETE",
                      headers={"X-Auth-User-Id": "ou_forged"})
    record("伪造头的 DELETE 被拒", status in (401, 403), f"HTTP {status}")

    status, _ = fetch(f"{base}/api/projects/owner", method="POST",
                      headers={"X-Auth-User-Id": "ou_forged",
                               "Content-Type": "application/json"},
                      body=json.dumps({"keys": ["file:index.html"],
                                       "ownerId": "ou_forged"}).encode())
    record("伪造头的批量指定负责人被拒", status in (401, 403), f"HTTP {status}")

    # 需求 2.15：X-Admin-Token 彻底失效
    print("\n[4] 需求 2.15 · X-Admin-Token 已无认证能力")
    s1, _ = fetch(f"{base}/api/files")
    s2, _ = fetch(f"{base}/api/files", headers={"X-Admin-Token": "whatever"})
    record("携带任意 X-Admin-Token 的结果与不携带一致",
           s1 == s2, f"{s1} vs {s2}")

    # 需求 9：应急通道仅回环
    print("\n[5] 需求 9 · 应急通道仅在回环地址监听")
    status, _ = fetch(f"http://127.0.0.1:{args.emergency_port}/emergency/login")
    record("回环地址可达应急通道", status == 200, f"HTTP {status}")

    try:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
        import file_manager
        lan_ip = file_manager.get_local_ip()
    except Exception:
        lan_ip = ""
    if lan_ip and not lan_ip.startswith("127."):
        status, _ = fetch(f"http://{lan_ip}:{args.emergency_port}/emergency/login")
        record(f"局域网地址 {lan_ip} 无法连接应急通道",
               status == -1, f"结果 {status}")
    else:
        record("局域网地址探测已跳过（未取到非回环 IP）", True, "skipped")

    # 汇总
    total = len(_results)
    failed = [r for r in _results if not r[1]]
    print("\n" + "=" * 64)
    print(f"结果：{total - len(failed)} 通过 / {len(failed)} 失败")
    if failed:
        print("\n失败项：")
        for name, _ok, detail in failed:
            print(f"  - {name}  {detail}")
    print("=" * 64)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
