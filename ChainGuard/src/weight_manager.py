from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal

from src.config_loader import load_risk_weights, load_thresholds
from src.game_model import _PAYOFF_WEIGHTS_DEFAULTS


@dataclass(frozen=True)
class WeightSet:
    values: dict[str, float]
    source: Literal["expert", "calibrated"]
    sample_size: int
    method: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.values,
            "_source": self.source,
            "_sample_size": self.sample_size,
            "_method": self.method,
            "_note": self.note,
        }


class WeightManager:
    MIN_SAMPLES: int = 5

    def resolve_inventory_risk_weights(
        self,
        historical_data: Iterable[dict] | None = None,
    ) -> WeightSet:
        """返回决策实际使用的库存风险权重——**始终是专家先验**。

        这里过去会调 `calibrate_inventory_risk_weights` 并把结果直接用于决策，
        存在两个严重问题：

        1. 那个函数用事后结果当特征、与标签构成目标泄漏（详见
           `src/feature_reconstruction.py` 模块说明），算出的权重不可信；
        2. 更要命的是它**自动生效、没有任何人工审批**，与产品对外承诺的
           "校准只给建议、人工确认后才影响决策"直接矛盾。

        现在：主决策流水线只用专家先验。数据驱动权重必须走
        `webapi/calibration_governance` 的治理流程——经样本外验证 + 管理员确认后
        写入租户配置，由 `TenantContextBuilder` 读取生效。本类不再自行校准。
        """
        _ = historical_data  # 保留入参以兼容既有调用点；权重不再依赖它
        expert = load_risk_weights()["inventory_risk_weights"]
        values = {key: float(value) for key, value in expert.items()}
        _validate_plain_values(values)
        _validate_normalized(values, "inventory_risk_weights")
        return WeightSet(
            values=values,
            source="expert",
            sample_size=0,
            method="expert_yaml",
            note="主流水线使用专家先验；数据驱动权重需经校准治理流程人工确认后生效",
        )

    def resolve_decision_score_weights(
        self,
        historical_data: Iterable[dict] | None = None,
    ) -> WeightSet:
        _ = historical_data
        expert = load_risk_weights()["decision_score_weights"]
        values = {k: float(v) for k, v in expert.items()}
        _validate_plain_values(values)
        _validate_normalized(values, "decision_score_weights")
        return WeightSet(
            values=values,
            source="expert",
            sample_size=0,
            method="expert_yaml",
            note="历史数据不含决策维度级评分标注，暂无数据驱动校准路径",
        )

    def resolve_payoff_weights(self) -> WeightSet:
        payoff_weights = load_risk_weights().get(
            "payoff_weights",
            _PAYOFF_WEIGHTS_DEFAULTS,
        )
        values = {k: float(v) for k, v in payoff_weights.items()}
        _validate_plain_values(values)
        return WeightSet(
            values=values,
            source="expert",
            sample_size=0,
            method="expert_yaml",
            note="博弈收益权重由专家配置，当前版本不支持数据驱动校准",
        )


    def resolve_trigger_threshold(
        self,
        historical_data: Iterable[dict] | None,
        inventory_weights: dict[str, float],
    ) -> dict[str, Any]:
        """Resolve inventory_risk_trigger threshold.

        与权重同理：触发阈值也不再由主流水线自行校准。

        旧实现调 `calibrate_trigger_threshold`（取失败样本风险指数的 P25），
        既依赖泄漏口径的代理特征，又只优化召回、不计误报代价，且同样自动生效。
        数据驱动阈值现在走治理流程（成本敏感优化 + 人工确认），见
        `src/supervised_calibration.calibrate_trigger_threshold_cost_sensitive`。
        """
        _ = (historical_data, inventory_weights)
        expert_trigger = load_thresholds()["inventory_warning"]["inventory_risk_trigger"]
        return {
            "value": float(expert_trigger),
            "_source": "expert",
            "_sample_size": 0,
            "_method": "expert_yaml",
            "_note": "主流水线使用专家阈值；数据驱动阈值需经校准治理流程人工确认后生效",
        }


def _validate_plain_values(values: dict[str, float]) -> None:
    bad_keys = [key for key in values if key.startswith("_")]
    if bad_keys:
        raise ValueError(f"weight values must not contain metadata keys: {bad_keys}")


def _validate_normalized(values: dict[str, float], name: str) -> None:
    total = sum(values.values())
    if not 0.9999 <= total <= 1.0001:
        raise ValueError(f"{name} must sum to 1.0, got {total:.6f}")
