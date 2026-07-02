"""
Configuration for WebApps Link Manager

配置说明：
- BASE_DIR: 项目根目录（webapps 目录的父目录）
- SERVER_DIR: 服务端代码目录
- WEBAPPS_DIR: 用户 HTML 文件存放目录
- METADATA_FILE: 元数据存储文件路径
- HOST/PORT: 服务监听地址（默认 0.0.0.0:8080）
- VERSION: 语义化版本号（主版本.迭代号）
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
ITERATION_FILE = BASE_DIR / "version_iteration.json"

# Server settings
HOST = "0.0.0.0"
PORT = 8080

# Base version (manually set for major releases)
# Auto-increment builds on top of this
VERSION_BASE = "1.0"

def get_version() -> str:
    """Get version with auto-incremented iteration."""
    # Load or create iteration
    if ITERATION_FILE.exists():
        try:
            iteration = json.loads(ITERATION_FILE.read_text()).get("iteration", 0)
        except:
            iteration = 0
    else:
        iteration = 0

    # Increment for next build
    iteration += 1

    # Save new iteration
    ITERATION_FILE.write_text(json.dumps({"iteration": iteration}))

    return f"{VERSION_BASE}.{iteration}"

# Get current version
VERSION = get_version()

# Ensure webapps directory exists
WEBAPPS_DIR.mkdir(parents=True, exist_ok=True)
VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
