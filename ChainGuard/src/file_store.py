"""进程间安全的 JSON/JSONL 文件落盘原语。

本模块解决两个此前散落在各处、且都会**静默**丢数据的问题：

1. **非原子写**：``Path.write_text()`` 先截断再写。写到一半崩溃/被抢占，
   文件就剩半行。而读侧（如 ``ModelRegistry.load_all``）对解析失败的行
   一律 ``continue`` 跳过——坏行不报错、不告警，直接消失。
2. **无锁的读-改-写**：``load_all() -> 修改 -> _write_all()`` 这个序列在
   并发下是经典的 lost update。注意这不只是多进程问题：FastAPI 把同步
   ``def`` 端点丢进 anyio 线程池执行，**单个 uvicorn worker 内部就并发**，
   所以"只起一个 worker"并不能规避。

修法沿用仓库里已有的惯用法（``HistoryPipeline.save_watermark``）：
写同目录临时文件再 ``os.replace()``——该调用在 Windows 与 POSIX 上都是原子的。
锁用**旁挂文件** ``<path>.lock``，而不是锁目标文件本身：Windows 上无法
替换一个仍被持有句柄的文件，锁在目标上会让 ``os.replace()`` 直接失败。

不引入 filelock/portalocker 依赖——标准库足够，且部署侧少一个第三方包。
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

__all__ = ["atomic_write_text", "file_lock", "LockTimeout"]


class LockTimeout(RuntimeError):
    """在超时窗口内没能拿到文件锁。

    宁可抛错也不静默继续：拿不到锁还往下写，就退化成本模块要消除的那种丢写。
    """


# 单次等待轮询间隔与默认超时。默认 10s 远大于这些文件（KB 级）的写入耗时，
# 又不至于让误持锁的进程把请求线程钉死到网关超时。
_POLL_SECONDS = 0.01
_DEFAULT_TIMEOUT = 10.0


@contextmanager
def file_lock(path: str | Path, *, timeout: float = _DEFAULT_TIMEOUT) -> Iterator[None]:
    """对 ``path`` 取排他锁，通过旁挂的 ``<path>.lock`` 实现。

    跨平台方式统一为"独占创建锁文件"（``O_CREAT | O_EXCL``）：这是原子的，
    且不依赖 msvcrt/fcntl 的平台分支，也不受网络文件系统上 flock 语义差异影响。
    """
    target = Path(path)
    lock_path = target.with_name(target.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + timeout
    fd: int | None = None
    last_error: OSError | None = None
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        # Windows 上删除是"延迟"的：持有者 unlink 之后、最后一个句柄关闭之前，
        # 文件处于 delete-pending，此时 O_EXCL 打开返回 ERROR_ACCESS_DENIED
        # （PermissionError），而不是 FileExistsError。只接 FileExistsError 会让
        # 等锁的线程直接崩掉——这正是本模块要消除的那种偶发失败。
        except (FileExistsError, PermissionError) as error:
            last_error = error
            if time.monotonic() >= deadline:
                raise LockTimeout(
                    f"等待文件锁超时（{timeout}s）：{lock_path}"
                    f"（最后一次失败：{type(last_error).__name__}: {last_error}）。"
                    "若确认无其他写者，删除该锁文件后重试。"
                ) from last_error
            time.sleep(_POLL_SECONDS)

    try:
        # 写入持有者信息，便于排查残留锁到底是谁留下的。
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        # 释放即删除。持有者崩溃会留下残留锁——这是"独占创建"方案的已知代价，
        # 换来的是无平台分支。残留锁会以 LockTimeout 显式暴露，不会静默丢写。
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> None:
    """原子地把 ``text`` 全量写入 ``path``。

    读者要么看到旧内容、要么看到新内容，绝不会看到写了一半的文件。
    临时文件必须与目标同目录——跨卷时 ``os.replace()` 不是原子操作。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # 带 pid 后缀，避免两个写者的临时文件互相踩（它们各自持锁时不会并发，
    # 但未持锁的调用方也可能用到本函数）。
    tmp_path = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        with open(tmp_path, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            # 元数据落盘前发生断电，replace 后仍可能读到空文件；fsync 消除该窗口。
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
