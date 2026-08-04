"""
Configuration for WebApps Link Manager

配置说明：
- BASE_DIR: 项目根目录（webapps 目录的父目录）
- SERVER_DIR: 服务端代码目录
- WEBAPPS_DIR: 用户 HTML 文件存放目录
- METADATA_FILE: 元数据存储文件路径
- HOST/PORT: 服务监听地址（默认 0.0.0.0:8080）
- VERSION: 系统版本号（主版本.次版本.修订号）
         —— 唯一真相源为 changelog.json 中最新一条记录，
            通过 changelog.add_entry() 自动递增，无需手动维护。

认证相关配置（飞书 SSO）：
- 取值优先级：真实环境变量 > 项目根目录 .env 文件 > 代码内默认值
- App Secret 等凭据只从环境变量/.env 读取，不入代码库（.gitignore 已排除 .env）
- 校验入口是 validate_auth_config()，**不在模块导入期执行** ——
  changelog.py 等命令行工具也会 import config，导入期退出会让它们无法运行。
  由 app.py 的启动入口在 app.run() 之前显式调用。
"""
import os
import json
import sys
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent.parent.resolve()
SERVER_DIR = Path(__file__).parent.resolve()
WEBAPPS_DIR = BASE_DIR / "webapps"
VERSIONS_DIR = BASE_DIR / "versions"  # Historical version files storage
METADATA_FILE = BASE_DIR / "metadata.json"

# Server settings
HOST = "0.0.0.0"
PORT = 8080

# Changelog file path (single source of truth for the version number)
CHANGELOG_FILE = BASE_DIR / "changelog.json"

# Fallback version when no changelog entries exist yet
DEFAULT_VERSION = "1.0.0"


def get_current_version() -> str:
    """
    Read the current system version from changelog.json (latest entry).
    changelog.json is the single source of truth; the version auto-grows
    whenever a new entry is appended via changelog.add_entry().
    Falls back to DEFAULT_VERSION when no changelog exists.
    """
    try:
        if CHANGELOG_FILE.exists():
            data = json.loads(CHANGELOG_FILE.read_text(encoding="utf-8"))
            recorded = data.get("last_recorded_version", "")
            if recorded:
                return recorded
            entries = data.get("entries", [])
            if entries:
                return entries[0].get("version", DEFAULT_VERSION)
    except (json.JSONDecodeError, IOError, OSError):
        pass
    return DEFAULT_VERSION


# Current system version (derived from changelog.json)
VERSION = get_current_version()

# Ensure webapps directory exists
WEBAPPS_DIR.mkdir(parents=True, exist_ok=True)
VERSIONS_DIR.mkdir(parents=True, exist_ok=True)


# ── .env loading ─────────────────────────────────────────────────────────────

ENV_FILE = BASE_DIR / ".env"


def _load_dotenv(path: Path = ENV_FILE) -> None:
    """
    Load KEY=VALUE pairs from `.env` into os.environ.

    Deliberately minimal (no python-dotenv dependency — the project keeps its
    runtime deps at flask + bcrypt). Real environment variables always win, so
    a shell export can override the file without editing it.

    Supported: blank lines, `#` comments, optional `export ` prefix,
    single/double quoted values. Malformed lines are skipped silently rather
    than crashing startup on a stray character.
    """
    try:
        if not path.exists():
            return
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            # Real env vars take precedence over the file
            os.environ.setdefault(key, value)
    except OSError:
        # An unreadable .env must not prevent the app (or changelog.py) from
        # starting; missing required values are caught by validate_auth_config().
        pass


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    """Read an environment variable, trimming surrounding whitespace."""
    return (os.environ.get(name, default) or "").strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _env_list(name: str, default: str = "") -> tuple:
    """Parse a comma-separated env var into a tuple of non-empty items."""
    raw = _env(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


# ── Auth configuration ───────────────────────────────────────────────────────

# Deployment environment: "development" | "production".
# Controls the Secure cookie attribute and the allowed callback URL set.
DEPLOY_ENV = _env("DEPLOY_ENV", "development").lower()
IS_PRODUCTION = DEPLOY_ENV == "production"

# How the app resolves the caller's identity:
#   embedded — single process, no gateway. Identity comes ONLY from the session
#              cookie; every inbound X-Auth-* header is stripped and ignored.
#   gateway  — Nginx (or equivalent) terminates auth and injects X-Auth-*
#              headers. Trusted only when the peer address is in
#              TRUSTED_GATEWAY_IPS.
# Defaulting to "embedded" is the fail-safe choice: a missing/mistyped value
# must never make the app start trusting client-supplied identity headers.
AUTH_MODE = _env("AUTH_MODE", "embedded").lower() or "embedded"
VALID_AUTH_MODES = ("embedded", "gateway")

# Peer addresses allowed to supply X-Auth-* headers (gateway mode only).
TRUSTED_GATEWAY_IPS = _env_list("TRUSTED_GATEWAY_IPS", "127.0.0.1,::1")

# Public origins. In embedded mode these are optional and fall back to the
# request's own origin; in gateway mode they are required for absolute
# preview URLs and cross-domain handoff.
ADMIN_ORIGIN = _env("ADMIN_ORIGIN").rstrip("/")
PREVIEW_ORIGIN = _env("PREVIEW_ORIGIN").rstrip("/")

# Emergency admin channel: username/password login that survives a Feishu
# outage. MUST bind to a loopback address only.
EMERGENCY_BIND = _env("EMERGENCY_BIND", "127.0.0.1:8099")
EMERGENCY_ENABLED = _env_bool("EMERGENCY_ENABLED", True)
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost", "[::1]")

# Embedded-mode mitigation: serve uploaded prototypes with a sandbox CSP so a
# malicious prototype cannot read the management session from the same origin.
# Only relevant in embedded mode; gateway mode isolates by domain instead.
# Turning this off restores the pre-SSO risk level.
PREVIEW_SANDBOX = _env_bool("PREVIEW_SANDBOX", True)

# Feishu (Lark) self-built app credentials.
FEISHU_APP_ID = _env("FEISHU_APP_ID")
FEISHU_APP_SECRET = _env("FEISHU_APP_SECRET")

# HMAC key for signed credentials (handoff / project access tokens).
# In embedded mode a missing value is auto-generated and persisted by
# server/auth/signing.py so that already-issued credentials survive a restart.
AUTH_SIGNING_SECRET = _env("AUTH_SIGNING_SECRET")
AUTH_SECRET_FILE = BASE_DIR / ".auth_secret"

# Session storage (sessions / OAuth states / handoff credentials).
AUTH_SESSIONS_FILE = BASE_DIR / "auth_sessions.json"

# Session lifetimes, in seconds.
SESSION_IDLE_MAX = 7 * 24 * 60 * 60          # 604800 — sliding idle window
SESSION_ABSOLUTE_MAX = 30 * 24 * 60 * 60     # 2592000 — hard cap
SESSION_TOUCH_INTERVAL = 300                 # throttle last_seen_at writes
OAUTH_STATE_TTL = 10 * 60                    # OAuth state validity
HANDOFF_TTL = 60                             # cross-domain handoff credential
ACCESS_CREDENTIAL_TTL = 8 * 60 * 60          # project password access token
EMERGENCY_SESSION_TTL = 60 * 60              # fixed, never extended

# Feishu callback paths/URLs allowed for this deployment.
FEISHU_CALLBACK_PATH = "/auth/feishu/callback"
DEV_CALLBACK_URLS = (
    f"http://localhost:{PORT}{FEISHU_CALLBACK_PATH}",
    f"http://10.10.1.25:{PORT}{FEISHU_CALLBACK_PATH}",
)


def allowed_callback_urls() -> tuple:
    """
    The exact set of redirect_uri values this deployment may use.

    Production deliberately EXCLUDES the plain-HTTP development callbacks so
    nobody can downgrade the flow by pointing at a LAN address.
    """
    if IS_PRODUCTION:
        if not ADMIN_ORIGIN:
            return ()
        return (f"{ADMIN_ORIGIN}{FEISHU_CALLBACK_PATH}",)
    urls = list(DEV_CALLBACK_URLS)
    if ADMIN_ORIGIN:
        candidate = f"{ADMIN_ORIGIN}{FEISHU_CALLBACK_PATH}"
        if candidate not in urls:
            urls.append(candidate)
    return tuple(urls)


def emergency_host_port() -> tuple:
    """Split EMERGENCY_BIND into (host, port). Port falls back to 8099."""
    raw = EMERGENCY_BIND.strip()
    if raw.startswith("["):                 # bracketed IPv6, e.g. [::1]:8099
        host, _, rest = raw.partition("]")
        host = host.lstrip("[")
        port = rest.lstrip(":") or "8099"
    else:
        host, _, port = raw.rpartition(":")
        if not host:                        # no colon at all — treat as host
            host, port = raw, "8099"
        port = port or "8099"
    try:
        return host, int(port)
    except ValueError:
        return host, 8099


def is_loopback_host(host: str) -> bool:
    return host.strip().lower() in LOOPBACK_HOSTS


class ConfigError(Exception):
    """Raised for a configuration problem that must stop startup."""


def validate_auth_config() -> None:
    """
    Validate auth configuration. Raises ConfigError on any fatal problem.

    Called from the app's startup path BEFORE binding a port, so a
    misconfiguration results in "nobody can log in" rather than "anyone can
    impersonate anyone". Never called at import time — command line tools such
    as changelog.py import this module without needing Feishu credentials.

    Error messages name the offending variable but never echo its value.
    """
    problems = []

    if AUTH_MODE not in VALID_AUTH_MODES:
        problems.append(
            f"AUTH_MODE 取值非法（应为 {' 或 '.join(VALID_AUTH_MODES)}）"
        )

    if not FEISHU_APP_ID:
        problems.append("FEISHU_APP_ID 未设置或为空")
    if not FEISHU_APP_SECRET:
        problems.append("FEISHU_APP_SECRET 未设置或为空")

    if AUTH_MODE == "gateway":
        if not TRUSTED_GATEWAY_IPS:
            problems.append("gateway 模式下 TRUSTED_GATEWAY_IPS 不能为空")
        if not ADMIN_ORIGIN:
            problems.append("gateway 模式下 ADMIN_ORIGIN 不能为空")
        if not PREVIEW_ORIGIN:
            problems.append("gateway 模式下 PREVIEW_ORIGIN 不能为空")
        if not AUTH_SIGNING_SECRET:
            problems.append("gateway 模式下 AUTH_SIGNING_SECRET 必须显式设置")

    if IS_PRODUCTION and not allowed_callback_urls():
        problems.append("生产环境需要 ADMIN_ORIGIN 以确定允许的飞书回调地址")

    if EMERGENCY_ENABLED:
        host, _port = emergency_host_port()
        if not is_loopback_host(host):
            problems.append(
                f"EMERGENCY_BIND 的监听地址必须是回环地址"
                f"（{'/'.join(LOOPBACK_HOSTS[:3])}），当前配置为 {host}"
            )

    if problems:
        raise ConfigError("；".join(problems))


def abort_on_invalid_auth_config() -> None:
    """Validate and terminate the process on failure, without binding a port."""
    try:
        validate_auth_config()
    except ConfigError as e:
        sys.stderr.write(
            "\n[启动终止] 认证配置有误，进程未监听任何端口。\n"
            f"  原因：{e}\n"
            f"  请检查环境变量或 {ENV_FILE}（可参考 .env.example）。\n\n"
        )
        raise SystemExit(1)
