"""并发落盘回归测试。

这些用例锁住的是一类**静默**丢数据的缺陷：读-改-写不加锁 + 非原子写。
修复前的实测（24 线程并发 register）：24 条只活下来 1 条，另有 2 行 torn write
被 load_all 当坏行跳过，全程零异常。没有断言挡着，这种回退不会有人发现。

判据从第一性原理给：N 个写者各追加恰好 1 条唯一记录，则终态必须恰好 N 条、
且 id 互不重复。不从观测结果反推期望值。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.file_store import LockTimeout, atomic_write_text, file_lock
from src.model_registry import ModelRegistry
from src.signature_history import load_history, update_history

# 线程数取得足够大以稳定复现竞态：修复前的实现在 24 线程下丢写率 >95%。
CONCURRENCY = 24


def _run_concurrently(work, count: int = CONCURRENCY) -> list[BaseException]:
    """让 count 个线程在栅栏处对齐后同时进入临界区，最大化竞态窗口。"""
    barrier = threading.Barrier(count)
    errors: list[BaseException] = []

    def runner(index: int) -> None:
        try:
            barrier.wait()
            work(index)
        except BaseException as error:  # noqa: BLE001 - 汇总后统一断言
            errors.append(error)

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


def test_registry_concurrent_register_loses_nothing(tmp_path):
    registry = ModelRegistry(tmp_path / "model_registry.json")

    errors = _run_concurrently(
        lambda i: registry.register(f"snap-{i}", {"accuracy": float(i)}, notes=f"t{i}")
    )

    assert errors == []
    records = registry.load_all()
    assert len(records) == CONCURRENCY
    assert len({record.version_id for record in records}) == CONCURRENCY
    # 每个写者的 snapshot_version 都必须在，缺任何一个都是丢写而非乱序。
    assert {record.snapshot_version for record in records} == {
        f"snap-{i}" for i in range(CONCURRENCY)
    }


def test_registry_file_never_contains_torn_lines(tmp_path):
    """落盘文件的每一行都必须是完整 JSON——load_all 会静默跳过坏行，
    所以只断言 load_all 的条数不足以证明没有 torn write。"""
    path = tmp_path / "model_registry.json"
    registry = ModelRegistry(path)

    _run_concurrently(lambda i: registry.register(f"snap-{i}", {"accuracy": float(i)}))

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == CONCURRENCY
    for line in lines:
        json.loads(line)  # 任何一行解析失败即为写入被撕裂


def test_registry_concurrent_promote_keeps_exactly_one_stable(tmp_path):
    """promote_stable 也是读-改-写：并发提升后 is_stable 必须恰好一条为真。"""
    registry = ModelRegistry(tmp_path / "model_registry.json")
    versions = [
        registry.register(f"snap-{i}", {"accuracy": float(i)}).version_id
        for i in range(CONCURRENCY)
    ]

    errors = _run_concurrently(lambda i: registry.promote_stable(versions[i]))

    assert errors == []
    stable = [record for record in registry.load_all() if record.is_stable]
    assert len(stable) == 1
    assert len(registry.load_all()) == CONCURRENCY  # 提升不得吃掉任何记录


def test_signature_history_concurrent_updates_sum_exactly(tmp_path):
    """去重计数并发累加不得偏低——计数偏低只会放行重复数据，不会报错。"""
    source = SimpleNamespace(
        kind="enterprise",
        tenant_id="tenant_conc",
        audit_log_path=str(tmp_path / "audit_log.tenant_conc.jsonl"),
    )
    record = {
        "event_type": "port_shutdown",
        "affected_material_id": "MAT-001",
        "supplier_id": "SUP-1",
    }

    errors = _run_concurrently(lambda _i: update_history(source, [dict(record)]))

    assert errors == []
    counts = load_history(source)
    # 同一条记录写 CONCURRENCY 次，其唯一签名的计数必须恰好等于 CONCURRENCY。
    assert sum(counts.values()) == CONCURRENCY


def test_atomic_write_replaces_wholesale(tmp_path):
    target = tmp_path / "nested" / "payload.json"
    atomic_write_text(target, '{"a": 1}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

    atomic_write_text(target, '{"b": 2}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"b": 2}
    # 临时文件不得残留在目标目录。
    assert [p.name for p in target.parent.iterdir()] == ["payload.json"]


def test_atomic_write_leaves_no_tmp_on_failure(tmp_path):
    target = tmp_path / "payload.json"
    atomic_write_text(target, "original")

    class Unserializable:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    with pytest.raises(TypeError):
        atomic_write_text(target, Unserializable())  # type: ignore[arg-type]

    # 原文件必须完好，且不留临时文件。
    assert target.read_text(encoding="utf-8") == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["payload.json"]


def test_file_lock_is_mutually_exclusive(tmp_path):
    """锁必须真的互斥——否则上面所有并发用例都可能只是碰巧通过。"""
    target = tmp_path / "guarded.json"
    overlapping = []
    inside = 0
    state_lock = threading.Lock()

    def critical(_i: int) -> None:
        nonlocal inside
        with file_lock(target, timeout=30):
            with state_lock:
                inside += 1
                overlapping.append(inside)
            # 拉长临界区，让未加锁的实现必然出现重叠。
            threading.Event().wait(0.005)
            with state_lock:
                inside -= 1

    errors = _run_concurrently(critical)
    assert errors == []
    assert max(overlapping) == 1  # 任何时刻临界区内只允许一个线程


def test_file_lock_times_out_instead_of_writing_unguarded(tmp_path):
    """拿不到锁必须显式抛错。静默继续写就退化成本模块要消除的丢写。"""
    target = tmp_path / "guarded.json"
    with file_lock(target):
        with pytest.raises(LockTimeout):
            with file_lock(target, timeout=0.05):
                pass


def test_file_lock_releases_on_exception(tmp_path):
    target = tmp_path / "guarded.json"
    with pytest.raises(ValueError):
        with file_lock(target):
            raise ValueError("boom")
    # 异常路径若不释放锁，这里会 LockTimeout。
    with file_lock(target, timeout=1):
        pass
    assert not Path(str(target) + ".lock").exists()
