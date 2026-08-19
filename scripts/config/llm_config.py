#!/usr/bin/env python3
"""LLM API 配置，供各脚本共用。通过 .env 环境变量注入。"""

import os
from pathlib import Path

# 自动加载项目根目录 .env
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

# ── DeepSeek ─────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")

# ── OpenKey ──────────────────────────────────────────────────────
OPENKEY_API_KEY = os.getenv("OPENKEY_API_KEY", "")
OPENKEY_API_BASE = os.getenv("OPENKEY_API_BASE", "https://openkey.cloud/v1")

# ── 模型名 ──────────────────────────────────────────────────────
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
OPENKEY_MODEL = os.getenv("OPENKEY_MODEL", "deepseek-chat")

# ── 通用调用参数 ─────────────────────────────────────────────────
TEMPERATURE = 0.3
MAX_TOKENS = 4000
MAX_RETRIES = 3
SLEEP_BETWEEN = 1.0
