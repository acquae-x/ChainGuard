"""极简 .env 加载器（零依赖）。

config.py 的注释一直写着"部署环境必须通过 .env 注入签名密钥"，但此前没有任何
地方真的加载过 .env——只有 os.getenv。本模块补上这一环。

约定：
- **已存在的环境变量优先**。.env 只做补充，绝不覆盖调用方显式设置的值；
  否则测试、CI 与 start-demo 里设好的变量会被本地 .env 悄悄改掉。
- 文件不存在就静默跳过（开发与 CI 都不带 .env，必须是无副作用的）。
- 只做最小解析：`KEY=VALUE`、`#` 注释、可选 `export ` 前缀、可选成对引号。
  不支持变量插值与多行值——需要那些复杂度时应改用 python-dotenv，
  而不是让这里长成一个半吊子解析器。

安全：.env 已被 .gitignore 排除（根 .gitignore 与 ChainGuard/.gitignore 各有一条）。
密钥只应写在 .env，绝不写进任何被版本控制的文件。
"""

from __future__ import annotations

import os
from pathlib import Path

# ChainGuard/src/webapi/env_file.py → ChainGuard/
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def load_env_file(path: Path | None = None) -> int:
    """把 .env 里尚未设置的变量注入 os.environ，返回注入条数。"""
    target = path or _PROJECT_ROOT / ".env"
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0

    injected = 0
    for line in raw.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.startswith("export "):
            entry = entry[len("export "):].strip()
        key, separator, value = entry.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not key or key in os.environ:  # 已存在的环境变量优先
            continue
        os.environ[key] = _unquote(value.strip())
        injected += 1
    return injected
