"""锁住 .env 加载的三条安全属性。

这些不是功能测试，是防回归：.env 一旦覆盖了调用方显式设置的变量，
CI 与 start-demo 里设好的密钥会被开发机上的 .env 悄悄替换掉，
而且症状极难定位（"我明明设了 JWT_SECRET"）。
"""

import os

from src.webapi.env_file import load_env_file


def test_injects_missing_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("PROBE_ALPHA=from-file\n", encoding="utf-8")
    monkeypatch.delenv("PROBE_ALPHA", raising=False)

    assert load_env_file(env) == 1
    assert os.environ["PROBE_ALPHA"] == "from-file"


def test_existing_env_wins(tmp_path, monkeypatch):
    """已存在的环境变量优先——.env 只补充，绝不覆盖。"""
    env = tmp_path / ".env"
    env.write_text("PROBE_BETA=from-file\n", encoding="utf-8")
    monkeypatch.setenv("PROBE_BETA", "from-shell")

    assert load_env_file(env) == 0
    assert os.environ["PROBE_BETA"] == "from-shell"


def test_missing_file_is_noop(tmp_path):
    """开发与 CI 都不带 .env，文件不存在必须静默跳过而不是抛错。"""
    assert load_env_file(tmp_path / "does-not-exist.env") == 0


def test_parses_comments_export_and_quotes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# 注释行\n"
        "\n"
        "export PROBE_GAMMA=exported\n"
        'PROBE_DELTA="带 空格 的值"\n'
        "PROBE_EPSILON='单引号'\n"
        "没有等号的行会被跳过\n",
        encoding="utf-8",
    )
    for key in ("PROBE_GAMMA", "PROBE_DELTA", "PROBE_EPSILON"):
        monkeypatch.delenv(key, raising=False)

    assert load_env_file(env) == 3
    assert os.environ["PROBE_GAMMA"] == "exported"
    assert os.environ["PROBE_DELTA"] == "带 空格 的值"
    assert os.environ["PROBE_EPSILON"] == "单引号"
