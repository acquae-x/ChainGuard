"""1-2 回归：限流计数桶必须跨 uvicorn worker 共享。

缺陷形态：``Limiter()`` 不传 ``storage_uri`` → slowapi 退化为 ``memory://`` →
镜像默认的 ``--workers 4`` 让每个进程各持一份计数桶，``5/minute`` 实际放宽到
``4×5/minute``，且进程重启即清零。

因此本文件的核心用例**必须真的跨进程**：单进程内怎么测都测不出这个缺陷（单进程
下 ``memory://`` 与共享存储行为完全一致）。下面每个 worker 都是独立的
``sys.executable`` 子进程，各自 import ``src.webapi.limits``、各自构造 Limiter，
只共享 ``RATE_LIMIT_STORAGE_URI`` 指向的存储。

默认共享介质是 ``sharedfile://``（见 tests/_shared_rate_limit_storage.py 的说明：
换成 redis 时同一份断言逐字成立）。设置 ``CHAINGUARD_TEST_REDIS_URL`` 即可让同一
组用例真的跑在 Redis 上。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from _shared_rate_limit_storage import build_uri
from src.webapi.limits import (
    MEMORY_STORAGE_URI,
    RateLimitStorageNotConfigured,
    resolve_rate_limit_storage_uri,
)


LIMIT = "5/minute"
ATTEMPTS_PER_WORKER = 4
WORKERS = 3

# 子进程脚本：完整走应用自己的限流器构造路径（读 RATE_LIMIT_STORAGE_URI →
# resolve → Limiter(storage_uri=...)），而不是在测试里另建一个 Limiter，
# 否则测的就不是被修的那段代码了。
_WORKER_SCRIPT = """
import json, os, sys
sys.path[:] = json.loads(os.environ["CG_TEST_SYSPATH"])
import limits

if os.environ.get("CG_TEST_LOAD_SHARED_STORAGE") == "1":
    import _shared_rate_limit_storage  # noqa: F401  注册 sharedfile:// scheme

from src.webapi.limits import RATE_LIMIT_STORAGE_URI, limiter

item = limits.parse(os.environ["CG_TEST_LIMIT"])
key = os.environ["CG_TEST_KEY"]
allowed = sum(1 for _ in range(int(os.environ["CG_TEST_ATTEMPTS"])) if limiter.limiter.hit(item, key))
print(json.dumps({"pid": os.getpid(), "allowed": allowed, "uri": RATE_LIMIT_STORAGE_URI}))
"""


def _run_worker(storage_uri: str, key: str, *, load_shared_storage: bool) -> dict:
    """跑一个独立进程的 worker，返回它自己放行了几次。"""
    env = {
        **os.environ,
        "CG_TEST_SYSPATH": json.dumps(sys.path),
        "CG_TEST_LIMIT": LIMIT,
        "CG_TEST_KEY": key,
        "CG_TEST_ATTEMPTS": str(ATTEMPTS_PER_WORKER),
        "CG_TEST_LOAD_SHARED_STORAGE": "1" if load_shared_storage else "0",
        "RATE_LIMIT_STORAGE_URI": storage_uri,
    }
    completed = subprocess.run(
        [sys.executable, "-c", _WORKER_SCRIPT],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode == 0, f"worker 进程失败:\n{completed.stdout}\n{completed.stderr}"
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _run_fleet(storage_uri: str, key: str, *, load_shared_storage: bool) -> list[dict]:
    return [_run_worker(storage_uri, key, load_shared_storage=load_shared_storage) for _ in range(WORKERS)]


@pytest.fixture()
def shared_storage_uri(tmp_path_factory) -> str:
    """优先用真实 Redis；没有就用跨进程文件存储替身。"""
    configured = os.getenv("CHAINGUARD_TEST_REDIS_URL", "").strip()
    if configured:
        return configured
    return build_uri(tmp_path_factory.mktemp("rate-limit-storage") / "buckets.json")


def test_rate_limit_bucket_is_shared_across_worker_processes(shared_storage_uri: str):
    """3 个独立进程 × 4 次尝试 打在同一个 5/minute 桶上，总放行必须恰好 5 次。"""
    key = f"cg-shared-{uuid.uuid4().hex}"
    using_redis = shared_storage_uri.startswith("redis")

    results = _run_fleet(shared_storage_uri, key, load_shared_storage=not using_redis)

    pids = {result["pid"] for result in results}
    assert len(pids) == WORKERS, f"worker 未真正分处不同进程：{pids}"
    assert all(result["uri"] == shared_storage_uri for result in results)

    total_allowed = sum(result["allowed"] for result in results)
    assert total_allowed == 5, (
        f"{WORKERS} 个 worker 共放行 {total_allowed} 次，限流额度未被共享 "
        f"（每进程独立计数会放行 {min(ATTEMPTS_PER_WORKER, 5) * WORKERS} 次）"
    )
    # 第一个 worker 就把额度用掉 4 次，后面两个只该再拿到 1 次和 0 次——
    # 这条锁住"桶是同一个"，而不只是"总数恰好对上"。
    assert [result["allowed"] for result in results] == [4, 1, 0]


def test_memory_storage_does_not_share_across_processes(tmp_path):
    """探针有效性自证：同一套 harness 指向 memory:// 时必须测出"各算各的"。

    没有这条，上面那个用例通过也不能说明它挡得住回归——它可能只是恰好在任何
    配置下都成立。
    """
    key = f"cg-memory-{uuid.uuid4().hex}"

    results = _run_fleet(MEMORY_STORAGE_URI, key, load_shared_storage=False)

    assert [result["allowed"] for result in results] == [ATTEMPTS_PER_WORKER] * WORKERS, (
        "memory:// 下每个进程都应拿到完整额度；若这里也变成共享，说明本文件的"
        "多进程断言其实没在区分两种配置"
    )


def test_explicit_configuration_wins_over_backend_detection():
    assert resolve_rate_limit_storage_uri("redis://cache:6379/0", "postgresql+psycopg://x/y") == "redis://cache:6379/0"
    # 显式写 memory:// 是被允许的降级路径（本地开发 / CI 单进程）
    assert resolve_rate_limit_storage_uri("memory://", "postgresql+psycopg://x/y") == MEMORY_STORAGE_URI
    # 前后空白不应把"已配置"误判成"未配置"
    assert resolve_rate_limit_storage_uri("  redis://cache:6379/0  ", "") == "redis://cache:6379/0"


def test_sqlite_backend_falls_back_to_memory_storage():
    """开发/演示是单进程单端口，进程内计数与共享计数等价，不该逼开发者起 Redis。"""
    assert resolve_rate_limit_storage_uri("", "sqlite:///./chainguard.db") == MEMORY_STORAGE_URI
    assert resolve_rate_limit_storage_uri("", "SQLite:///C:/tmp/x.db") == MEMORY_STORAGE_URI


def test_production_backend_without_shared_storage_refuses_to_start():
    """非 SQLite 后端 + 未配置共享存储 = 拒绝启动，绝不静默退回进程内存。"""
    with pytest.raises(RateLimitStorageNotConfigured) as error:
        resolve_rate_limit_storage_uri("", "postgresql+psycopg://user:pw@postgres:5432/cg")
    assert "RATE_LIMIT_STORAGE_URI" in str(error.value)


def test_app_limiter_is_constructed_with_the_resolved_storage_uri():
    """限流器实际用的 uri 必须来自 resolve，而不是 slowapi 的默认值。"""
    from src.webapi import limits as module

    assert module.limiter._storage_uri == module.RATE_LIMIT_STORAGE_URI


def test_compose_provides_redis_backed_shared_storage():
    compose = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")

    assert "\n  redis:" in compose, "多 worker 部署需要 redis 服务承载共享限流计数桶"
    assert "RATE_LIMIT_STORAGE_URI" in compose and "redis://redis:6379" in compose
    # 与 postgres 服务同款的运维约定：健康检查、持久化、资源上限缺一不可
    assert "redis-cli ping" in compose
    assert "redisdata:/data" in compose and "--appendonly" in compose
    assert "mem_limit: 512m" in compose
    # api 必须等 redis 就绪；否则首个请求期的限流会打在一个连不上的存储上
    redis_dependency = compose.split("\n  api:", 1)[1].split("\n  web:", 1)[0]
    assert "redis:\n        condition: service_healthy" in redis_dependency
