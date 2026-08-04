"""
pytest 公共夹具。

所有测试都在临时目录里跑：会话存储、metadata、签名密钥全部指向 tmp_path，
真实数据一个字节都不会被碰到。这一点很重要 —— 本项目的"数据库"就是几个
JSON 文件，测试一旦写错路径就会污染生产数据。
"""
import sys
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).parent.parent.resolve()
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

import config  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把所有落盘路径重定向到 tmp_path，并重建各模块的 store 实例。"""
    monkeypatch.setattr(config, "AUTH_SESSIONS_FILE", tmp_path / "auth_sessions.json")
    monkeypatch.setattr(config, "AUTH_SECRET_FILE", tmp_path / ".auth_secret")
    monkeypatch.setattr(config, "METADATA_FILE", tmp_path / "metadata.json")
    monkeypatch.setattr(config, "AUTH_SIGNING_SECRET", "")
    monkeypatch.setattr(config, "AUTH_MODE", "embedded")
    monkeypatch.setattr(config, "IS_PRODUCTION", False)

    from atomic_store import AtomicJSONStore
    import metadata
    monkeypatch.setattr(metadata, "_store",
                        AtomicJSONStore(config.METADATA_FILE, empty_default={}))

    from auth import session_store, signing
    monkeypatch.setattr(session_store, "_store",
                        AtomicJSONStore(config.AUTH_SESSIONS_FILE,
                                        empty_default=dict(session_store._EMPTY)))
    signing.reset_secret_cache()

    yield tmp_path

    signing.reset_secret_cache()
