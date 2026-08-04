"""
正确性属性测试（对应 design.md 的 Property 1~11）。

这些不是单点用例，而是对随机输入反复验证的不变式。没有引入 hypothesis
（项目约定不加依赖），用 random 自己生成足够多的样本，并固定种子保证可复现。
"""
import json
import random
import sys
import time
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).parent.parent.resolve()
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

import config
import metadata
import permissions
from permissions import Actor, can_manage
from auth import session_store, signing

RNG = random.Random(20260804)      # 固定种子，失败可复现
SAMPLES = 200


def _rand_id(prefix="ou_"):
    return prefix + "".join(RNG.choice("abcdef0123456789") for _ in range(16))


def _rand_ip():
    return ".".join(str(RNG.randint(1, 254)) for _ in range(4))


# ── Property 2 / 3：权限判定等价式与 IP 无关性 ───────────────────────────────

def test_property2_can_manage_equivalence():
    """can_manage(p, a) == a.is_admin or (owner_id != "" and owner_id == a.user_id)"""
    for _ in range(SAMPLES):
        owner_id = RNG.choice(["", "", _rand_id()])
        actor_id = RNG.choice([owner_id, _rand_id()]) or _rand_id()
        is_admin = RNG.random() < 0.3
        is_super = is_admin and RNG.random() < 0.5
        project = {"owner_id": owner_id, "uploader_ip": _rand_ip()}
        actor = Actor(user_id=actor_id, name="n", is_admin=is_admin, is_super=is_super)

        expected = is_admin or (owner_id != "" and owner_id == actor_id)
        assert can_manage(project, actor) is expected, (project, actor)


def test_property2_ownerless_denied_for_non_admin():
    """无负责人项目对任意非管理员恒为假。"""
    for _ in range(SAMPLES):
        project = {"owner_id": RNG.choice(["", None]), "uploader_ip": _rand_ip()}
        actor = Actor(user_id=_rand_id(), name="n", is_admin=False)
        assert can_manage(project, actor) is False


def test_property3_result_independent_of_ip():
    """任意改动 uploader_ip 都不改变 can_manage 结果。"""
    for _ in range(SAMPLES):
        owner_id = RNG.choice(["", _rand_id()])
        actor = Actor(user_id=_rand_id(), name="n",
                      is_admin=RNG.random() < 0.3)
        base = {"owner_id": owner_id, "uploader_ip": _rand_ip()}
        baseline = can_manage(base, actor)
        for _ in range(5):
            mutated = dict(base)
            mutated["uploader_ip"] = _rand_ip()
            mutated["versions"] = {"V1": {"uploader_ip": _rand_ip()}}
            assert can_manage(mutated, actor) is baseline


def test_unauthenticated_never_manages():
    """未认证（actor 为 None 或空 user_id）一律为假。"""
    project = {"owner_id": _rand_id()}
    assert can_manage(project, None) is False
    assert can_manage(project, Actor(user_id="", name="", is_admin=True)) is False


# ── Property 7：会话过期边界闭合 ─────────────────────────────────────────────

def test_property7_expiry_boundaries(sandbox):
    sid = session_store.create_session("ou_1", "甲", session_store.DOMAIN_ADMIN)
    now = int(time.time())

    def set_times(last_seen=None, expires_at=None):
        with session_store._store.transaction() as data:
            record = data["sessions"][sid]
            if last_seen is not None:
                record["last_seen_at"] = last_seen
            if expires_at is not None:
                record["expires_at"] = expires_at

    # 空闲边界：等于 SESSION_IDLE_MAX 有效，+1 秒失效
    set_times(last_seen=now - config.SESSION_IDLE_MAX, expires_at=now + 10 ** 6)
    assert session_store.get_valid_session(sid, session_store.DOMAIN_ADMIN) is not None
    set_times(last_seen=now - config.SESSION_IDLE_MAX - 1)
    assert session_store.get_valid_session(sid, session_store.DOMAIN_ADMIN) is None

    # 绝对过期边界：now == expires_at 有效，now > expires_at 失效
    sid2 = session_store.create_session("ou_2", "乙", session_store.DOMAIN_ADMIN)
    with session_store._store.transaction() as data:
        data["sessions"][sid2]["expires_at"] = int(time.time())
    assert session_store.get_valid_session(sid2, session_store.DOMAIN_ADMIN) is not None
    with session_store._store.transaction() as data:
        data["sessions"][sid2]["expires_at"] = int(time.time()) - 1
    assert session_store.get_valid_session(sid2, session_store.DOMAIN_ADMIN) is None


def test_property6_validity_monotonically_decreasing(sandbox):
    """一旦被判为无效，之后任意时刻都不会再变有效。"""
    sid = session_store.create_session("ou_1", "甲", session_store.DOMAIN_ADMIN)
    with session_store._store.transaction() as data:
        data["sessions"][sid]["last_seen_at"] = 0
    assert session_store.get_valid_session(sid, session_store.DOMAIN_ADMIN) is None
    # 反复查询不会"复活"
    for _ in range(5):
        assert session_store.get_valid_session(sid, session_store.DOMAIN_ADMIN) is None


# ── Property 10：双域会话不互通 ─────────────────────────────────────────────

def test_property10_domain_sessions_not_interchangeable(sandbox):
    admin_sid = session_store.create_session("ou_1", "甲", session_store.DOMAIN_ADMIN)
    preview_sid = session_store.create_session("ou_1", "甲", session_store.DOMAIN_PREVIEW)

    assert session_store.get_valid_session(admin_sid, session_store.DOMAIN_PREVIEW) is None
    assert session_store.get_valid_session(preview_sid, session_store.DOMAIN_ADMIN) is None
    assert session_store.get_valid_session(admin_sid, session_store.DOMAIN_ADMIN) is not None
    assert session_store.get_valid_session(preview_sid, session_store.DOMAIN_PREVIEW) is not None


def test_domain_mismatch_does_not_refresh_last_seen(sandbox):
    """域不匹配时不得刷新活跃时间（需求 4.11）。"""
    sid = session_store.create_session("ou_1", "甲", session_store.DOMAIN_ADMIN)
    stale = int(time.time()) - 400          # 超过 300 秒节流窗口
    with session_store._store.transaction() as data:
        data["sessions"][sid]["last_seen_at"] = stale
    session_store.get_valid_session(sid, session_store.DOMAIN_PREVIEW)
    record = session_store._store.load()["sessions"][sid]
    assert record["last_seen_at"] == stale


# ── Property 5：一次性凭证不可重放 ───────────────────────────────────────────

def test_property5_state_single_use(sandbox):
    for _ in range(30):
        state = session_store.create_state("/", "http://localhost:8080/cb")
        assert session_store.consume_state(state) is not None
        for _ in range(3):
            assert session_store.consume_state(state) is None


def test_property5_handoff_single_use(sandbox):
    for _ in range(30):
        user_id = _rand_id()
        jti = session_store.register_handoff(user_id)
        assert session_store.consume_handoff(jti, user_id) is True
        assert session_store.consume_handoff(jti, user_id) is False


def test_handoff_rejects_user_mismatch(sandbox):
    jti = session_store.register_handoff("ou_owner")
    assert session_store.consume_handoff(jti, "ou_other") is False
    # 被拒后仍应保持可用（未被误标记为已使用）
    assert session_store.consume_handoff(jti, "ou_owner") is True


# ── Property 8：访问凭证与密码强绑定 ─────────────────────────────────────────

def test_property8_credential_bound_to_password_version(sandbox):
    for _ in range(50):
        user_id = _rand_id()
        key = f"file:{_rand_id('p_')}.html"
        old_hash = "$2b$12$" + "".join(RNG.choice("abcdef0123456789") for _ in range(22))
        new_hash = "$2b$12$" + "".join(RNG.choice("abcdef0123456789") for _ in range(22))

        token = signing.issue_access_credential(user_id, key, old_hash)
        assert signing.verify_access_credential(token, user_id, key, old_hash)
        # 密码变更 → 立即失效
        assert not signing.verify_access_credential(token, user_id, key, new_hash)
        # 密码移除 → 立即失效
        assert not signing.verify_access_credential(token, user_id, key, None)
        # 换人、换项目 → 失效
        assert not signing.verify_access_credential(token, _rand_id(), key, old_hash)
        assert not signing.verify_access_credential(token, user_id, key + "x", old_hash)


def test_signature_tampering_rejected(sandbox):
    token = signing.sign({"typ": "t", "exp": int(time.time()) + 60, "v": 1})
    body, _, sig = token.partition(".")
    assert signing.verify(token, "t") is not None
    assert signing.verify(f"{body}.{'A' * len(sig)}", "t") is None
    assert signing.verify(f"{body[:-1]}X.{sig}", "t") is None
    assert signing.verify(body, "t") is None
    assert signing.verify("", "t") is None
    assert signing.verify(token, "other-typ") is None


# ── Property 4：迁移幂等与字段保全 ───────────────────────────────────────────

def _random_metadata():
    meta = {}
    for _ in range(RNG.randint(1, 8)):
        key = f"file:{_rand_id('proj_')}.html"
        entry = {
            "title": "标题" + str(RNG.randint(1, 999)),
            "uploader_ip": _rand_ip(),
            "upload_time": "2026-07-01T10:00:00",
            "current_version": "V1",
            "versions": {},
        }
        if RNG.random() < 0.4:
            entry["owner_id"] = _rand_id()
            entry["owner_name"] = "已有负责人"
        if RNG.random() < 0.5:
            entry["password"] = "$2b$12$abcdefghijklmnopqrstuv"
        for i in range(RNG.randint(1, 3)):
            entry["versions"][f"V{i + 1}"] = {
                "upload_time": "2026-07-01T10:00:00",
                "uploader_ip": _rand_ip(),
            }
        meta[key] = entry
    return meta


def test_property4_migration_idempotent_and_preserving(sandbox):
    import migrate_identity

    for _ in range(20):
        original = _random_metadata()
        metadata.save_metadata(json.loads(json.dumps(original)))

        migrate_identity.migrate()
        first = json.loads(json.dumps(metadata.load_metadata()))
        migrate_identity.migrate()
        second = metadata.load_metadata()

        # 幂等：两次结果逐字段一致
        assert first == second

        for key, entry in original.items():
            got = first[key]
            # 字段保全：除新增两个字段外原值不变
            for field, value in entry.items():
                if field == "versions":
                    continue
                assert got[field] == value, (key, field)
            # 已有非空 owner_id 不被覆盖
            if entry.get("owner_id"):
                assert got["owner_id"] == entry["owner_id"]
            # 版本级 uploader_ip 一个不少
            for version, record in entry["versions"].items():
                assert got["versions"][version]["uploader_ip"] == record["uploader_ip"]
                assert "owner_id" in got["versions"][version]


# ── Property 9：凭据不外泄 ───────────────────────────────────────────────────

def test_property9_audit_redacts_credentials(tmp_path, monkeypatch):
    import audit
    monkeypatch.setattr(audit, "AUDIT_FILE", tmp_path / "audit.jsonl")

    secrets_like = [
        "t-g1044ghJRUIJ" + "a" * 40,
        "u-" + "b" * 45,
        "cli_aafb2c20633a1bc4",
        "x" * 50,
    ]
    for value in secrets_like:
        audit.log("admin", f"登录 {value}", actor="谁", ip="1.1.1.1",
                  target=value, detail=f"token={value}")

    content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    for value in secrets_like:
        assert value not in content, f"凭据未被脱敏：{value[:12]}…"
    assert "***" in content


def test_feishu_error_carries_no_credentials():
    from auth import feishu
    err = feishu.FeishuError(20003, "code is invalid", "exchange_token")
    text = str(err)
    assert config.FEISHU_APP_SECRET not in text
    assert "20003" in text
