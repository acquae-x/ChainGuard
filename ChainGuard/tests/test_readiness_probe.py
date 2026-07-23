"""就绪探针回归测试。

/healthz 与 /readyz 此前零覆盖，而它们决定滚动发布是否判定成功。
这里锁住的具体缺陷：少配令牌签名密钥的部署，数据库连得通、/readyz 因此返回 ready，
发布判定成功、旧副本下线——直到第一个用户登录才 500。就绪探针必须在接流量之前
拦下这种配置错误，而不是把它推迟到运行期。
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

import src.api
from src.api import app
from src.webapi.config import settings

client = TestClient(app)


def _patch_settings(monkeypatch, **overrides):
    """替换 src.api 模块里的 settings 名字绑定。

    Settings 是 frozen dataclass，不能就地 setattr；而 api.py 用的是
    `from src.webapi.config import settings` 这种直接名字绑定，改 config 模块
    的属性也影响不到它。所以只能整体换掉 src.api.settings 指向的对象。
    """
    monkeypatch.setattr(src.api, "settings", dataclasses.replace(settings, **overrides))


def test_healthz_is_unauthenticated_liveness():
    """存活探针必须免鉴权：要鉴权的探针在鉴权依赖挂掉时会误报进程已死。"""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_ready_when_database_and_signing_key_present():
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


@pytest.mark.parametrize(
    ("algorithm", "blanked_field"),
    [
        ("HS256", "jwt_secret"),
        ("RS256", "jwt_rs256_private_key"),
    ],
)
def test_readyz_503_when_signing_key_missing(monkeypatch, capsys, algorithm, blanked_field):
    """按签名算法取对应的密钥字段——RS256 用私钥，其余用对称密钥。

    对外只断言 503：全局异常处理器会把所有 5xx 的 detail 换成通用文案，
    这是刻意的防信息泄漏，不该在这里被推翻。真正给运维看的原因在结构化日志里。
    """
    _patch_settings(monkeypatch, jwt_algorithm=algorithm, **{blanked_field: ""})

    resp = client.get("/readyz")

    assert resp.status_code == 503
    assert resp.json()["code"] == "CG-0503"
    # 探针失败必须留下可定位的原因，否则运维只能看到一个没有上下文的 503。
    assert "jwt_signing_key_missing" in capsys.readouterr().out


def test_readyz_ignores_the_key_the_active_algorithm_does_not_use():
    """反向断言，防止探针写成"任一密钥为空就 503"这种过度收敛的假实现。"""
    # 探针有效性自证：若下面这条断言无论如何都成立，上一个用例就不能证明什么。
    assert settings.jwt_algorithm != "RS256"
    assert settings.jwt_rs256_private_key == ""  # HS256 部署不会配 RS256 私钥
    resp = client.get("/readyz")
    assert resp.status_code == 200


def test_metrics_endpoint_is_not_marked_deprecated():
    """config/prometheus.yml 实际抓取 /metrics，config/alerts.yml 的规则挂在它导出的
    指标上。它一旦被标 deprecated，OpenAPI 就在向运维谎报这个接入点即将消失。"""
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/metrics"]["get"].get("deprecated") is not True
