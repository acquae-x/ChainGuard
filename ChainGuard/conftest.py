"""全仓库共用的测试引导，必须在导入应用模块前生效。

本文件放在 pytest rootdir（pytest.ini 所在目录），因此 `tests/` 与 `benchmarks/`
都会加载它。此前这些设置只存在于 tests/conftest.py，于是 `pytest benchmarks/`
既拿不到隔离的 DATABASE_URL（收集阶段就被 validate_database_target 拒绝），
也拿不到大模型守卫（开发机 .env 里的真实 DEEPSEEK_API_KEY 会让每次决策真的
发起远程调用，p50≈11s，把阈值 2000ms 的性能断言打成"性能回归"的假象）。

settings 是 import 时冻结的 dataclass，因此环境变量必须先于任何
`src.webapi.*` / `src.api` 导入生效——rootdir 的 conftest 在收集阶段最先执行，
满足该约束。
"""

import atexit
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent

os.environ.setdefault("JWT_SECRET", "test-only-signing-key-not-for-deployment")
os.environ.setdefault("SEED_DEMO_PASSWORD", "test-runtime-password")
# SSO client_secret 与 ERP 凭证同款 Fernet 加密；不给密钥则保存路径按设计直接 503。
os.environ.setdefault("CHAINGUARD_ENCRYPTION_KEY", "test-only-encryption-key-not-for-deployment")

# 测试与基准都绝不打真实大模型接口。
#
# 开发机上 ChainGuard/.env 里可能放着真实 DEEPSEEK_API_KEY，而 config.py 在导入时
# 会加载 .env——于是 TextGenerator() 默认解析成 deepseek，任何没有 mock urlopen 的
# 用例都会真的发起远程调用：测试变慢、不再自洽、还消耗真实额度。
#
# 用赋值而非 pop：load_env_file 只注入"环境里尚不存在"的键，pop 掉反而会被 .env
# 重新填上。显式置空才能借"已有环境变量优先"这条规则挡住它。
# 需要验证 deepseek 分支的用例自己传 provider/api_key，不受这里影响。
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["CHAINGUARD_LLM_PROVIDER"] = "ollama"

if "DATABASE_URL" not in os.environ:
    # Keep both the database and pytest's own temporary files under a stable,
    # workspace-owned parent.  On Windows the system temp directory (and an
    # old pytest-owned basetemp) can retain an ACL from another sandbox user,
    # which made the otherwise isolated test database fail during collection.
    _TEST_RUNTIME_ROOT = PROJECT_ROOT / "test_tmp"
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


# --- 干净检出自举 -------------------------------------------------------------
# demo_assets 下的 CSV/PDF/xlsx 都在版本库里，唯独 *.db 被 .gitignore 排除，
# 于是新 clone / worktree / CI 上有 24 个用例失败。失败形态是 scanned=0 这类
# 空结果而非报错，极易被误判成代码回归（实测踩过）。
#
# 这里在收集阶段补齐该库。只在缺失时生成（约 12s），已存在则完全不动；生成走
# --db-only 等价路径，不碰任何受版本控制的资产。
_DEMO_DB = PROJECT_ROOT / "demo_assets" / "enterprise" / "database" / "chainguard_enterprise_demo.db"

if not _DEMO_DB.exists():
    print(f"[conftest] 演示数据库缺失，正在生成：{_DEMO_DB}", file=sys.stderr)
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_enterprise_demo_data.py"), "--db-only"],
        cwd=PROJECT_ROOT,
        check=True,
    )


# 下面两个隔离 fixture 一律走 tmp_path_factory，不用 tmp_path。
# tests/test_classifier_pipeline.py 与 tests/test_experience_pipeline.py 各自定义了
# 同名的 tmp_path fixture 覆盖 pytest 内置版本，且返回的是**相对**路径；autouse
# fixture 若依赖 tmp_path，在这两个模块里就会拿到那个相对路径，把 PROJECT_ROOT
# patch 成相对路径后落盘位置会被二次嵌套（实测打挂 test_experience_pipeline 两条）。
# tmp_path_factory 无人覆盖，且同样受 pytest.ini 的 --basetemp 约束。


@pytest.fixture(autouse=True)
def _isolate_model_registry(tmp_path_factory, monkeypatch):
    """把模型注册表的默认落盘路径重定向到 tmp_path，避免测试写脏受版本控制的文件。

    data/model_registry.json 是受版本控制的 append-only 日志。
    src/model_comparison.py::_register_best_model 用无参 ModelRegistry()（默认相对路径
    data/model_registry.json）注册"本次比较的最佳模型"，而 tests/test_model_comparison.py
    有 12 处 compare_models() 调用——跑一次 pytest 就往仓库文件里追加几十行，工作区
    因此长期是脏的。src/drift_history.py、src/drift_monitor.py 里也有同样的无参调用。

    修法不逐个打补丁，而是拦在 ModelRegistry.__init__ 解析相对路径的那一步：
    `self.path = target if target.is_absolute() else PROJECT_ROOT / target`
    —— PROJECT_ROOT 是调用时才查找的模块全局，改它即可一次覆盖全部默认路径写入。
    （注意默认参数 DEFAULT_REGISTRY_PATH 在 def 时就已绑定，改那个常量无效。）
    显式传绝对路径的用例不受影响，它们走 is_absolute() 分支。
    """
    import src.model_registry

    monkeypatch.setattr(
        src.model_registry, "PROJECT_ROOT", tmp_path_factory.mktemp("model_registry")
    )


@pytest.fixture(autouse=True)
def _isolate_experience_cards(tmp_path_factory, monkeypatch):
    """经验卡片同样重定向到 tmp_path，理由与 _isolate_model_registry 完全相同。

    data/experience_cards.json 是受版本控制的文件，而 demo_source() 给的
    experience_cards_path 是相对路径 "data/experience_cards.json"；任何跑完整
    orchestrator 的用例都会经 save_experience_card() 写进仓库这份文件。
    结果是跑一次 pytest 工作区就变脏，且这种脏在 git status 里与真实改动无从区分。

    拦截点同样选 src.learning._resolve_path 依赖的模块全局 PROJECT_ROOT
    （默认参数 "data/experience_cards.json" 在 def 时已绑定，改不动）。
    显式传绝对路径的用例走 is_absolute() 分支，不受影响。
    """
    import src.learning

    monkeypatch.setattr(
        src.learning, "PROJECT_ROOT", tmp_path_factory.mktemp("experience_cards")
    )
