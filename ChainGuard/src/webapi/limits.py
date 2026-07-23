"""限流器构造：多 worker 部署下计数桶必须在进程外共享。

背景（1-2）：Dockerfile 与 docker-compose 默认都是 ``--workers 4``。slowapi 的
``Limiter`` 不传 ``storage_uri`` 时退化为 ``memory://``——每个 uvicorn worker 各持
一份独立的字典计数桶。于是 ``LOGIN_IP_RATE_LIMIT=5/minute`` 名义上限 5 次，实际
上限是 4×5=20 次（负载均衡把同一 IP 轮询到 4 个进程），且进程重启即清零。对撞库
防线而言这不是"略微宽松"，而是把 IP 侧防线的预算直接放大了 worker 倍数。

修法是把计数桶挪到 Redis。但"默默退回内存"正是原缺陷的形态，所以这里对
**未配置** 的行为做显式裁决，而不是给一个安静的兜底：

* 显式配置了 ``RATE_LIMIT_STORAGE_URI`` —— 一律照用，包括显式写 ``memory://``。
  这是本地开发与 CI 的降级路径：写明即视为部署方已知晓并承担单进程假设。
* 未配置且数据库是 SQLite —— 判定为开发/演示模式（``start-demo`` 单进程单端口），
  退回 ``memory://`` 并记一条可检索的 ``rate_limit_storage_in_memory`` 事件。
* 未配置且数据库不是 SQLite —— 判定为生产部署，**拒绝启动**。生产编排默认多
  worker，此时静默退回内存等同于关掉限流，宁可起不来也不能带病上线。

拒绝启动发生在 import 期（``src.api`` 导入本模块时），因此进程根本不会开始监听，
不存在"起来了但限流是坏的"这个中间态。
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from src.observability import log_event

from .config import settings


MEMORY_STORAGE_URI = "memory://"


class RateLimitStorageNotConfigured(RuntimeError):
    """生产部署缺少共享限流存储；调用方不应捕获它，应当让进程起不来。"""


def resolve_rate_limit_storage_uri(configured: str, database_url: str) -> str:
    """决定限流计数桶落在哪里；规则见模块文档。"""
    explicit = (configured or "").strip()
    if explicit:
        return explicit
    if (database_url or "").strip().lower().startswith("sqlite"):
        # 开发/演示：单进程，进程内计数与共享计数等价。
        log_event("rate_limit_storage_in_memory", reason="sqlite_development_backend")
        return MEMORY_STORAGE_URI
    raise RateLimitStorageNotConfigured(
        "RATE_LIMIT_STORAGE_URI 未配置，而当前数据库后端不是 SQLite（判定为生产部署）。"
        "生产编排默认 --workers>1，进程内限流计数桶会把限流额度按 worker 数放大，"
        "等同于关闭限流。请指向共享存储（例如 redis://redis:6379/0）；"
        "确知单进程运行时可显式设置 RATE_LIMIT_STORAGE_URI=memory:// 承担该风险。"
    )


RATE_LIMIT_STORAGE_URI = resolve_rate_limit_storage_uri(
    settings.rate_limit_storage_uri, settings.database_url
)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["120/minute"],
    storage_uri=RATE_LIMIT_STORAGE_URI,
)
