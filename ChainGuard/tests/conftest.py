"""测试进程的非生产配置，必须在导入应用模块前设置。

P2-15：pytest 必须使用隔离的临时 DATABASE_URL，禁止污染仓库默认的 chainguard.db。
settings 是 import 时冻结的 dataclass，因此这里的环境变量必须先于任何
`src.webapi.*` / `src.api` 导入生效（conftest 在收集阶段最先执行，满足该约束）。
"""

import atexit
import os
import sqlite3
import uuid
from pathlib import Path


os.environ.setdefault("JWT_SECRET", "test-only-signing-key-not-for-deployment")
os.environ.setdefault("SEED_DEMO_PASSWORD", "test-runtime-password")

if "DATABASE_URL" not in os.environ:
    # Keep both the database and pytest's own temporary files under a stable,
    # workspace-owned parent.  On Windows the system temp directory (and an
    # old pytest-owned basetemp) can retain an ACL from another sandbox user,
    # which made the otherwise isolated test database fail during collection.
    _TEST_RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "test_tmp"
    _TEST_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    # Do not use tempfile.mkdtemp here.  On managed Windows runners it creates
    # an owner-only child ACL even though the workspace parent is writable.
    _TEST_DB_PATH = str(_TEST_RUNTIME_ROOT / f"chainguard-test-{os.getpid()}-{uuid.uuid4().hex}.db")
    # src/db.py 对不存在的 SQLite 文件按"未知租户"拒绝，先落一个空库文件
    sqlite3.connect(_TEST_DB_PATH).close()
    os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.replace(os.sep, '/')}"

    @atexit.register
    def _cleanup_test_db() -> None:
        # Windows 下 SQLite 句柄可能延迟释放，清理失败不应让测试进程报错
        try:
            Path(_TEST_DB_PATH).unlink(missing_ok=True)
        except OSError:
            pass
