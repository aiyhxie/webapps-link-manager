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
"""
import os
import json
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
