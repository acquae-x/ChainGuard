from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal

from src.config_loader import load_risk_weights
from src.game_model import _PAYOFF_WEIGHTS_DEFAULTS
from src.parameter_calibration import calibrate_inventory_risk_weights


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
        records = list(historical_data or [])
        raw = calibrate_inventory_risk_weights(records)
        sample_size = int(raw.get("_sample_size", 0))
        note = str(raw.get("_calibration_note", ""))
        values = {k: float(v) for k, v in raw.items() if not k.startswith("_")}
        source: Literal["expert", "calibrated"] = (
            "expert" if "返回专家默认权重" in note else "calibrated"
        )
        _validate_plain_values(values)
        _validate_normalized(values, "inventory_risk_weights")
        return WeightSet(
            values=values,
            source=source,
            sample_size=sample_size,
            method=str(raw.get("_method", "pearson_correlation")),
            note=note or "库存风险权重由历史样本校准或专家默认配置提供",
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


def _validate_plain_values(values: dict[str, float]) -> None:
    bad_keys = [key for key in values if key.startswith("_")]
    if bad_keys:
        raise ValueError(f"weight values must not contain metadata keys: {bad_keys}")


def _validate_normalized(values: dict[str, float], name: str) -> None:
    total = sum(values.values())
    if not 0.9999 <= total <= 1.0001:
        raise ValueError(f"{name} must sum to 1.0, got {total:.6f}")
