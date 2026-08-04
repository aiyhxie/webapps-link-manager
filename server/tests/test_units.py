"""
单元测试：签名凭证、会话、用户档案与管理员名单、应急通道、配置校验。
"""
import sys
import time
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).parent.parent.resolve()
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

import config
import metadata
import user_directory
from auth import emergency, identity, session_store, signing


# ── 配置校验 ─────────────────────────────────────────────────────────────────

def test_invalid_auth_mode_rejected(monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "bogus")
    monkeypatch.setattr(config, "FEISHU_APP_ID", "cli_x")
    monkeypatch.setattr(config, "FEISHU_APP_SECRET", "s")
    with pytest.raises(config.ConfigError) as e:
        config.validate_auth_config()
    assert "AUTH_MODE" in str(e.value)


def test_missing_credentials_rejected(monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "embedded")
    monkeypatch.setattr(config, "FEISHU_APP_ID", "")
    monkeypatch.setattr(config, "FEISHU_APP_SECRET", "")
    with pytest.raises(config.ConfigError) as e:
        config.validate_auth_config()
    message = str(e.value)
    assert "FEISHU_APP_ID" in message and "FEISHU_APP_SECRET" in message


def test_error_message_never_echoes_secret(monkeypatch):
    """错误说明只报变量名，不带取值。"""
    monkeypatch.setattr(config, "AUTH_MODE", "gateway")
    monkeypatch.setattr(config, "FEISHU_APP_ID", "cli_x")
    monkeypatch.setattr(config, "FEISHU_APP_SECRET", "super-secret-value")
    monkeypatch.setattr(config, "AUTH_SIGNING_SECRET", "")
    monkeypatch.setattr(config, "ADMIN_ORIGIN", "")
    monkeypatch.setattr(config, "PREVIEW_ORIGIN", "")
    with pytest.raises(config.ConfigError) as e:
        config.validate_auth_config()
    assert "super-secret-value" not in str(e.value)


def test_emergency_non_loopback_rejected(monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "embedded")
    monkeypatch.setattr(config, "FEISHU_APP_ID", "cli_x")
    monkeypatch.setattr(config, "FEISHU_APP_SECRET", "s")
    monkeypatch.setattr(config, "EMERGENCY_ENABLED", True)
    monkeypatch.setattr(config, "EMERGENCY_BIND", "0.0.0.0:8099")
    with pytest.raises(config.ConfigError) as e:
        config.validate_auth_config()
    assert "回环" in str(e.value)


@pytest.mark.parametrize("raw,expected", [
    ("127.0.0.1:8099", ("127.0.0.1", 8099)),
    ("localhost:9000", ("localhost", 9000)),
    ("[::1]:8099", ("::1", 8099)),
    ("127.0.0.1", ("127.0.0.1", 8099)),
    ("127.0.0.1:notaport", ("127.0.0.1", 8099)),
])
def test_emergency_bind_parsing(monkeypatch, raw, expected):
    monkeypatch.setattr(config, "EMERGENCY_BIND", raw)
    assert config.emergency_host_port() == expected


def test_production_excludes_http_dev_callbacks(monkeypatch):
    """生产环境的允许回调列表必须排除 http 开发地址（需求 12.9）。"""
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "ADMIN_ORIGIN", "https://app.example.com")
    urls = config.allowed_callback_urls()
    assert urls == ("https://app.example.com/auth/feishu/callback",)
    assert all(not u.startswith("http://") for u in urls)


def test_development_includes_dev_callbacks(monkeypatch):
    monkeypatch.setattr(config, "IS_PRODUCTION", False)
    monkeypatch.setattr(config, "ADMIN_ORIGIN", "")
    urls = config.allowed_callback_urls()
    assert "http://localhost:8080/auth/feishu/callback" in urls


# ── 签名凭证 ─────────────────────────────────────────────────────────────────

def test_exp_boundary_inclusive(sandbox):
    now = int(time.time())
    token = signing.sign({"typ": "t", "exp": now})
    assert signing.verify(token, "t", now=now) is not None
    assert signing.verify(token, "t", now=now + 1) is None


def test_secret_persisted_with_600_permission(sandbox):
    import os
    signing.sign({"typ": "t", "exp": int(time.time()) + 10})
    assert config.AUTH_SECRET_FILE.exists()
    assert oct(os.stat(config.AUTH_SECRET_FILE).st_mode)[-3:] == "600"


def test_secret_stable_across_cache_reset(sandbox):
    token = signing.sign({"typ": "t", "exp": int(time.time()) + 60})
    signing.reset_secret_cache()
    assert signing.verify(token, "t") is not None


def test_gateway_mode_requires_explicit_secret(sandbox, monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "gateway")
    monkeypatch.setattr(config, "AUTH_SIGNING_SECRET", "")
    signing.reset_secret_cache()
    with pytest.raises(config.ConfigError):
        signing.sign({"typ": "t", "exp": int(time.time()) + 60})


def test_password_version_derivation():
    assert signing.password_version("$2b$12$abcdefghijklmnop") == "$2b$12$abcde"
    assert signing.password_version(None) == ""
    assert signing.password_version("") == ""


# ── 会话 ─────────────────────────────────────────────────────────────────────

def test_new_session_immediately_valid(sandbox):
    sid = session_store.create_session("ou_1", "甲", session_store.DOMAIN_ADMIN)
    record = session_store.get_valid_session(sid, session_store.DOMAIN_ADMIN)
    assert record is not None
    assert record["last_seen_at"] == record["created_at"]
    assert record["expires_at"] - record["created_at"] == config.SESSION_ABSOLUTE_MAX


def test_touch_throttled_within_window(sandbox):
    sid = session_store.create_session("ou_1", "甲", session_store.DOMAIN_ADMIN)
    before = session_store._store.load()["sessions"][sid]["last_seen_at"]
    session_store.touch(sid)
    after = session_store._store.load()["sessions"][sid]["last_seen_at"]
    assert before == after


def test_touch_updates_after_window(sandbox):
    sid = session_store.create_session("ou_1", "甲", session_store.DOMAIN_ADMIN)
    stale = int(time.time()) - config.SESSION_TOUCH_INTERVAL - 5
    with session_store._store.transaction() as data:
        data["sessions"][sid]["last_seen_at"] = stale
    session_store.touch(sid)
    assert session_store._store.load()["sessions"][sid]["last_seen_at"] > stale


def test_delete_session_idempotent(sandbox):
    sid = session_store.create_session("ou_1", "甲", session_store.DOMAIN_ADMIN)
    assert session_store.delete_session(sid) is True
    assert session_store.delete_session(sid) is False
    assert session_store.delete_session("") is False


def test_invalid_domain_rejected(sandbox):
    with pytest.raises(ValueError):
        session_store.create_session("ou_1", "甲", "bogus-domain")


def test_emergency_session_fixed_ttl(sandbox):
    sid = session_store.create_session(
        "emergency:admin", "admin（应急）", session_store.DOMAIN_ADMIN,
        kind=session_store.KIND_EMERGENCY, ttl=config.EMERGENCY_SESSION_TTL)
    record = session_store.get_valid_session(sid, session_store.DOMAIN_ADMIN)
    assert record["expires_at"] - record["created_at"] == config.EMERGENCY_SESSION_TTL
    assert record["kind"] == session_store.KIND_EMERGENCY


def test_bootstrap_recovers_from_corruption(sandbox):
    session_store.create_session("ou_1", "甲", session_store.DOMAIN_ADMIN)
    config.AUTH_SESSIONS_FILE.write_text("{ not json", encoding="utf-8")
    stats = session_store.bootstrap()          # 不应抛异常
    assert isinstance(stats, dict)


def test_bootstrap_clears_expired(sandbox):
    keep = session_store.create_session("ou_1", "甲", session_store.DOMAIN_ADMIN)
    drop = session_store.create_session("ou_2", "乙", session_store.DOMAIN_ADMIN)
    with session_store._store.transaction() as data:
        data["sessions"][drop]["last_seen_at"] = 0
    stats = session_store.bootstrap()
    assert stats["sessions_dropped"] >= 1
    assert session_store.get_valid_session(keep, session_store.DOMAIN_ADMIN) is not None


# ── 应急通道限流 ─────────────────────────────────────────────────────────────

def test_emergency_lockout_after_threshold(sandbox):
    account = "admin"
    for _ in range(4):
        session_store.emergency_record_failure(account)
    assert session_store.emergency_is_blocked(account)[0] is False
    session_store.emergency_record_failure(account)
    blocked, remain = session_store.emergency_is_blocked(account)
    assert blocked and 0 < remain <= 900


def test_emergency_success_clears_failures(sandbox):
    account = "admin"
    for _ in range(5):
        session_store.emergency_record_failure(account)
    session_store.emergency_clear_failures(account)
    assert session_store.emergency_is_blocked(account)[0] is False


def test_emergency_sliding_window_discards_old_failures(sandbox):
    """窗口外的旧失败作废 —— 否则一整天零散失败 5 次就会被误封。"""
    account = "admin"
    for _ in range(4):
        session_store.emergency_record_failure(account)
    with session_store._store.transaction() as data:
        data["emergency_failures"][account]["first_at"] = int(time.time()) - 1000
    session_store.emergency_record_failure(account)
    assert session_store.emergency_is_blocked(account)[0] is False


@pytest.mark.parametrize("password,ok", [
    ("Short1!", False),
    ("a" * 16, False),                       # 只有一类字符
    ("abcdefghijklmnop1", False),            # 两类
    ("Abcdefghijklmnop1", True),             # 三类
    ("Abcdefghijklmnop1!", True),            # 四类
    ("A1!" + "a" * 130, False),              # 超长
])
def test_emergency_password_strength(password, ok):
    assert emergency.validate_password_strength(password)[0] is ok


# ── 用户档案与管理员名单 ─────────────────────────────────────────────────────

def test_first_login_at_immutable(sandbox):
    first = user_directory.upsert_user("ou_1", "甲")["first_login_at"]
    user_directory.upsert_user("ou_1", "甲改名")
    record = user_directory.get_user("ou_1")
    assert record["first_login_at"] == first
    assert record["name"] == "甲改名"


def test_bootstrap_super_admin_only_once(sandbox):
    user_directory.upsert_user("ou_1", "甲")
    user_directory.upsert_user("ou_2", "乙")
    assert user_directory.bootstrap_super_admin("ou_1", "甲") is True
    assert user_directory.bootstrap_super_admin("ou_2", "乙") is False
    assert user_directory.super_admin_count() == 1


def test_add_admin_requires_directory_entry(sandbox):
    ok, message = user_directory.add_admin("ou_never_logged_in")
    assert ok is False and "登录" in message


def test_remove_admin_guards(sandbox):
    user_directory.upsert_user("ou_1", "甲")
    user_directory.upsert_user("ou_2", "乙")
    user_directory.bootstrap_super_admin("ou_1", "甲")
    user_directory.add_admin("ou_2")

    # 不能移除自己
    ok, _msg, code = user_directory.remove_admin("ou_1", operator_id="ou_1")
    assert (ok, code) == (False, 400)
    # 不在名单
    ok, _msg, code = user_directory.remove_admin("ou_absent", operator_id="ou_1")
    assert (ok, code) == (False, 404)
    # 普通管理员可移除
    ok, _msg, code = user_directory.remove_admin("ou_2", operator_id="ou_1")
    assert (ok, code) == (True, 200)
    # 最后一个超管不可移除
    ok, _msg, code = user_directory.remove_admin("ou_1", operator_id="ou_2")
    assert (ok, code) == (False, 400)


def test_legacy_admins_bucket_not_used_for_feishu(sandbox):
    with metadata._store.transaction() as meta:
        meta["_system_admins_"] = {"users": [{"username": "legacy",
                                             "password_hash": "$2b$x"}]}
    assert user_directory.is_admin("legacy") is False


def test_display_name_fallback_chain(sandbox):
    user_directory.upsert_user("ou_1", "甲")
    assert user_directory.get_display_name("ou_1", "快照") == "甲"
    assert user_directory.get_display_name("ou_missing", "快照") == "快照"
    assert user_directory.get_display_name("ou_missing") == "ou_missing"


# ── 身份头编解码 ─────────────────────────────────────────────────────────────

def test_user_name_header_is_ascii_and_bounded():
    encoded = identity.encode_user_name("谢勇华" * 100)
    assert encoded.isascii()
    assert len(encoded) <= 256
    # 截断不产生残缺的百分号序列
    import urllib.parse
    urllib.parse.unquote(encoded, errors="strict")


def test_user_name_truncation_keeps_whole_characters():
    """emoji 是 4 字节字符，编码后 12 个字符；截断必须落在字符边界上。"""
    import urllib.parse
    for name in ["谢" * 200, "🎉" * 100, ("谢勇华🎉" * 60)]:
        encoded = identity.encode_user_name(name)
        assert len(encoded) <= 256
        decoded = urllib.parse.unquote(encoded, errors="strict")
        assert name.startswith(decoded)


def test_user_name_roundtrip():
    for name in ["谢勇华", "Zhang San", "名字带空格 和符号!@#", "emoji🎉"]:
        encoded = identity.encode_user_name(name)
        assert identity.decode_user_name(encoded, "fallback") == name


def test_decode_falls_back_on_bad_input():
    assert identity.decode_user_name("%E4%B8", "ou_1") == "ou_1"
    assert identity.decode_user_name("", "ou_1") == "ou_1"


@pytest.mark.parametrize("value,ok", [
    ("ou_abc123", True),
    ("a" * 64, True),
    ("a" * 65, False),
    ("", False),
    ("ou abc", False),
    ("ou/abc", False),
    ("ou.abc", False),
    ("ou-abc_D9", True),
])
def test_user_id_validation(value, ok):
    assert identity._is_valid_user_id(value) is ok
