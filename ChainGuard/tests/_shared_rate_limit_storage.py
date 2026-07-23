"""进程外共享的限流存储替身，供多进程限流回归测试使用（1-2）。

为什么需要它：1-2 的回归测试要证明"多个 OS 进程共享同一计数桶"。真正的生产后端
是 Redis，但 CI 与开发机上既没有 redis-server 也没有 redis 客户端包；如果测试因此
被 skip，就等于没有回归防线——而这条防线要挡的恰恰是"看起来配好了、实际每个
worker 各算各的"这种静默失效。

于是这里注册一个 ``sharedfile://`` scheme，用文件系统做跨进程共享。它替换的**只是
共享介质**：被测对象仍然是 ``src.webapi.limits`` 里真实构造的 slowapi ``Limiter``、
真实的 ``limits`` 固定窗口策略、真实的 ``storage_from_string`` 解析路径。测试断言的
契约是"计数桶由 RATE_LIMIT_STORAGE_URI 指定的进程外存储承载"，把 uri 换成
``redis://`` 后同一份断言应当逐字成立——``tests/test_multiworker_rate_limit.py``
在设置了 ``CHAINGUARD_TEST_REDIS_URL`` 时就会真的这么跑。

同一份测试指向 ``memory://`` 必须失败（每进程各一桶），这一点由
``test_memory_storage_does_not_share_across_processes`` 显式守住——探针有效性
不能靠假设。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from limits.storage.base import Storage


def build_uri(path: str | Path) -> str:
    """把一个文件路径包装成本 scheme 的 uri（Windows 盘符路径同样适用）。"""
    return f"sharedfile://{Path(path).as_posix()}"


class SharedFileStorage(Storage):
    """JSON 文件承载的固定窗口计数桶；跨进程共享，够用即可。

    只实现 ``limits`` 基类要求的六个方法——slowapi 默认的固定窗口策略只用到
    ``incr`` / ``get`` / ``get_expiry``，滑动窗口那套额外协议不在契约范围内。
    """

    STORAGE_SCHEME = ["sharedfile"]

    def __init__(self, uri: str | None = None, wrap_exceptions: bool = False, **options: object) -> None:
        super().__init__(uri, wrap_exceptions=wrap_exceptions, **options)
        self.path = Path((uri or "").split("://", 1)[-1])
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def base_exceptions(self) -> type[Exception] | tuple[type[Exception], ...]:
        return OSError

    # --- 临界区 ---------------------------------------------------------------
    # 用 O_CREAT|O_EXCL 建锁文件做互斥：跨进程有效，且不依赖 fcntl / msvcrt
    # （本仓库同时要在 Windows 与 Linux CI 上跑）。
    def _acquire(self) -> None:
        deadline = time.monotonic() + 10.0
        while True:
            try:
                os.close(os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"shared rate limit storage lock stuck: {self.lock_path}")
                time.sleep(0.005)

    def _release(self) -> None:
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def _read(self) -> dict[str, dict[str, float]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, state: dict[str, dict[str, float]]) -> None:
        self.path.write_text(json.dumps(state), encoding="utf-8")

    @staticmethod
    def _live(entry: dict[str, float] | None) -> dict[str, float] | None:
        """过期条目当作不存在——固定窗口靠 key 的 TTL 翻窗。"""
        if entry is None or float(entry.get("expiry", 0)) <= time.time():
            return None
        return entry

    # --- Storage 协议 ---------------------------------------------------------
    def incr(self, key: str, expiry: int, amount: int = 1) -> int:
        self._acquire()
        try:
            state = self._read()
            entry = self._live(state.get(key))
            if entry is None:
                entry = {"count": 0.0, "expiry": time.time() + float(expiry)}
            entry["count"] = float(entry["count"]) + amount
            state[key] = entry
            self._write(state)
            return int(entry["count"])
        finally:
            self._release()

    def get(self, key: str) -> int:
        entry = self._live(self._read().get(key))
        return int(entry["count"]) if entry else 0

    def get_expiry(self, key: str) -> float:
        entry = self._live(self._read().get(key))
        return float(entry["expiry"]) if entry else time.time()

    def check(self) -> bool:
        return True

    def reset(self) -> int | None:
        self._acquire()
        try:
            count = len(self._read())
            self._write({})
            return count
        finally:
            self._release()

    def clear(self, key: str) -> None:
        self._acquire()
        try:
            state = self._read()
            state.pop(key, None)
            self._write(state)
        finally:
            self._release()
