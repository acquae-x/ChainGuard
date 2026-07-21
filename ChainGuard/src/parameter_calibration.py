"""Future calibration hooks for ChainGuard enterprise deployment.

The MVP intentionally avoids machine learning and real enterprise system
connections. These functions define stable extension points for a later phase
where ERP/WMS/TMS exports can be used to fit weights, thresholds, and decision
scoring rules.
"""

import math
from typing import Any

from src.config_loader import load_risk_weights, load_thresholds


def _outcome_score(status: str) -> float | None:
    """Map outcome_status to [0,1]. Returns None to skip unknown values."""
    return {"success": 1.0, "partial_success": 0.5, "failed": 0.0}.get(status)


def _pearson(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient. Returns 0.0 when undefined."""
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    return 0.0 if dx * dy == 0.0 else num / (dx * dy)


def _percentile(values: list[float], p: float) -> float:
    """Floor-index percentile. p in [0,1]."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = min(int(p * len(sorted_values)), len(sorted_values) - 1)
    return sorted_values[index]


def describe_calibration_inputs() -> list[str]:
    return [
        "ERP：采购订单、供应商交期、历史缺货记录、客户订单优先级",
        "WMS：库存快照、库龄、出入库流水、安全库存策略",
        "TMS：运输路线、港口节点、承运商时效、异常延误事件",
        "财务/服务数据：加急成本、延期罚金、客户服务等级协议",
    ]


def propose_calibration_workflow() -> list[str]:
    return [
        "清洗历史事件数据，统一物料、供应商、路线和客户订单口径",
        "回放历史中断场景，比较专家参数评分与真实履约结果",
        "校准库存风险权重、预警阈值和供应商延误惩罚系数",
        "输出新版本参数，并保留人工审批记录用于审计",
    ]


def calibrate_inventory_risk_weights(historical_data: Any) -> dict[str, Any]:
    """⚠ 已废弃：存在目标泄漏，结果不得用于决策。

    本函数用 `covered_demand_rate` / `lost_orders` / `actual_delay_hours` /
    `production_downtime_hours` 当特征，而标签 `outcome_status` 正是由这几个量
    算出来的——相关性接近同义反复，不是预测能力。此外它取相关系数绝对值
    （丢掉方向，保护性因子会被当成风险放大项），也不处理共线性。

    **替代方案**：`src.supervised_calibration.calibrate_weights_supervised`
    （事前特征 + 逻辑回归 + 样本外验证 + 校准不成立时明确拒绝）。

    保留本函数仅为历史对比用途（`scripts/diagnose_calibration.py` 并排展示两代方法），
    任何生产路径都不应再调用它。
    """
    records = list(historical_data) if historical_data else []
    expert = dict(load_risk_weights()["inventory_risk_weights"])
    keys = ["shortage_urgency", "order_importance", "transit_delay", "external_event"]

    xs = {key: [] for key in keys}
    ys = []
    for record in records:
        score = _outcome_score(record.get("outcome_status", ""))
        if score is None:
            continue

        coverage = float(record.get("covered_demand_rate", 0.5))
        delay = float(record.get("actual_delay_hours", 0))
        lost_orders = float(record.get("lost_orders", 0))
        downtime = float(record.get("production_downtime_hours", 0))

        xs["shortage_urgency"].append(max(0.0, min(1.0 - coverage, 1.0)))
        xs["order_importance"].append(lost_orders / (lost_orders + 1.0))
        xs["transit_delay"].append(max(0.0, min(delay / 72.0, 1.0)))
        xs["external_event"].append(max(0.0, min(downtime / 168.0, 1.0)))
        ys.append(1.0 - score)

    if len(ys) < 5:
        result = dict(expert)
        result["_sample_size"] = len(ys)
        result["_method"] = "pearson_correlation"
        result["_calibration_note"] = f"样本量不足（{len(ys)} < 5），返回专家默认权重"
        return result

    correlations = {key: abs(_pearson(values, ys)) for key, values in xs.items()}
    total = sum(correlations.values())
    if total == 0.0:
        result = dict(expert)
        result["_sample_size"] = len(ys)
        result["_method"] = "pearson_correlation"
        result["_calibration_note"] = "相关性全为零，返回专家默认权重"
        return result

    weights = {key: round(correlations[key] / total, 6) for key in keys}
    weights[keys[-1]] = round(1.0 - sum(weights[key] for key in keys[:-1]), 6)
    weights["_sample_size"] = len(ys)
    weights["_method"] = "pearson_correlation"
    weights["_calibration_note"] = f"基于 {len(ys)} 条历史决策的皮尔逊相关归一化建议"
    return weights


def calibrate_thresholds(historical_data: Any) -> dict[str, Any]:
    """⚠ 已废弃：分位数口径只优化召回、不计误报代价，且依赖泄漏特征。

    替代方案：`src.supervised_calibration.calibrate_trigger_threshold_cost_sensitive`
    （按期望代价最小选阈值，并报出召回/精确率/告警率）。
    """
    """Calibrate alert thresholds from failed or partially failed outcomes."""
    result = load_thresholds()
    records = list(historical_data) if historical_data else []

    failure_delays = [
        float(record["actual_delay_hours"])
        for record in records
        if record.get("outcome_status") in ("failed", "partial_success")
        and "actual_delay_hours" in record
    ]
    if len(failure_delays) < 5:
        return result

    yellow = _percentile(failure_delays, 0.25)
    red = _percentile(failure_delays, 0.10)
    if red >= yellow:
        red = yellow * 0.5

    result["inventory_warning"]["yellow_support_hours"] = round(yellow, 1)
    result["inventory_warning"]["red_support_hours"] = round(red, 1)
    return result


def evaluate_decision_outcomes(historical_decisions: Any) -> dict[str, Any]:
    """Evaluate historical decision outcomes from real outcome labels."""
    records = list(historical_decisions) if historical_decisions else []
    if not records:
        return {
            # 无样本时不得编造指标：过去这里返回 average_score 82 / success_rate 0.76，
            # 是凭空捏造的"演示用"数字，会被当成真实历史表现读走（P0-2 同源问题）。
            "status": "no_data",
            "sample_size": 0,
            "average_score": None,
            "success_rate": None,
            "key_findings": ["暂无历史决策结果样本，无法评估。"],
        }

    scored = []
    for record in records:
        score = _outcome_score(record.get("outcome_status", ""))
        if score is not None:
            scored.append((record, score))

    if not scored:
        return {
            "status": "calibrated",
            "sample_size": 0,
            "success_rate": 0.0,
            "average_human_rating": 0.0,
            "avg_covered_demand_rate": 0.0,
            "avg_actual_delay_hours": 0.0,
            "risk_weight_suggestions": calibrate_inventory_risk_weights(records),
            "threshold_suggestions": calibrate_thresholds(records),
            "key_findings": [
                "样本量 0 条，未发现可识别的 outcome_status。",
                "无法计算真实成功率、覆盖率和延误均值。",
                "权重和阈值建议已回退到专家默认配置。",
            ],
        }

    sample_size = len(scored)
    success_count = sum(1 for _, score in scored if score == 1.0)
    avg_rating = sum(float(record.get("human_rating", 3)) for record, _ in scored) / sample_size
    avg_coverage = sum(float(record.get("covered_demand_rate", 0)) for record, _ in scored) / sample_size
    avg_delay = sum(float(record.get("actual_delay_hours", 0)) for record, _ in scored) / sample_size
    risk_weights = calibrate_inventory_risk_weights(records)
    thresholds = calibrate_thresholds(records)

    return {
        "status": "calibrated",
        "sample_size": sample_size,
        "success_rate": round(success_count / sample_size, 4),
        "average_human_rating": round(avg_rating, 2),
        "avg_covered_demand_rate": round(avg_coverage, 4),
        "avg_actual_delay_hours": round(avg_delay, 2),
        "risk_weight_suggestions": risk_weights,
        "threshold_suggestions": thresholds,
        "key_findings": [
            f"样本量 {sample_size} 条，成功率 {success_count / sample_size:.1%}。",
            f"平均供给覆盖率 {avg_coverage:.1%}，平均实际延误 {avg_delay:.0f}h。",
            f"权重建议：shortage_urgency={risk_weights['shortage_urgency']:.2f}，"
            f"transit_delay={risk_weights['transit_delay']:.2f}。",
        ],
    }


def explain_simulation_limitations() -> str:
    return "当前 MVP 使用模拟数据和专家经验参数，真实落地需导入企业 ERP/WMS/TMS 历史数据进行校准。"


def calibrate_parameters_from_enterprise_data(historical_data: Any | None = None) -> dict[str, Any]:
    """Compatibility wrapper for the original MVP calibration placeholder."""
    return {
        "status": "placeholder",
        "message": explain_simulation_limitations(),
        "inventory_risk_weights": calibrate_inventory_risk_weights(historical_data),
        "thresholds": calibrate_thresholds(historical_data),
    }


def calibrate_trigger_threshold(
    historical_data: Any,
    weights: dict[str, float],
) -> dict[str, Any]:
    """Calibrate inventory_risk_trigger from failure/partial_success records.

    Uses the same feature proxy mapping as calibrate_inventory_risk_weights,
    but scales features to [0,100] to produce a proxy risk_index comparable
    to the live inventory_risk_index computed by calculate_inventory_risk().

    Proxy mapping (one record -> one proxy_risk_index value):
        coverage  = float(record.get("covered_demand_rate", 0.5))
        delay     = float(record.get("actual_delay_hours", 0))
        lost      = float(record.get("lost_orders", 0))
        downtime  = float(record.get("production_downtime_hours", 0))

        shortage  = max(0.0, min((1.0 - coverage) * 100, 100))
        order_imp = lost / (lost + 1.0) * 100
        transit   = max(0.0, min(delay / 72.0 * 100, 100))
        ext       = max(0.0, min(downtime / 168.0 * 100, 100))

        proxy_risk_index = (
            weights["shortage_urgency"] * shortage
            + weights["order_importance"] * order_imp
            + weights["transit_delay"] * transit
            + weights["external_event"] * ext
        )

    Only records with outcome_status in ("failed", "partial_success") are included.
    Returns _percentile(proxy_indices, 0.25) rounded to 1 decimal place.
    Rationale: P25 yields ~75% recall on real failure data vs 0% for expert default 70.
               This matches the P25 used in calibrate_thresholds() for yellow_support_hours.

    Fallback (< 5 failure/partial_success records):
        Returns expert YAML default with _source="expert".

    Returns:
        {
            "value": float,        # calibrated threshold or expert YAML default
            "_source": str,        # "calibrated" | "expert"
            "_sample_size": int,   # count of failure/partial_success records used
            "_method": str,        # "p25_failure_proxy_risk_index" | "expert_yaml"
            "_note": str,          # human-readable Chinese explanation
        }

    NOTE: Do NOT call _validate_normalized() on this result - "value" is a single
    threshold float, not a weight vector, and must not be constrained to sum to 1.
    """
    records = list(historical_data) if historical_data else []
    expert_trigger = float(
        load_thresholds()["inventory_warning"]["inventory_risk_trigger"]
    )

    proxy_indices: list[float] = []
    for record in records:
        if record.get("outcome_status") not in ("failed", "partial_success"):
            continue
        coverage = float(record.get("covered_demand_rate", 0.5))
        delay    = float(record.get("actual_delay_hours", 0))
        lost     = float(record.get("lost_orders", 0))
        downtime = float(record.get("production_downtime_hours", 0))

        shortage  = max(0.0, min((1.0 - coverage) * 100, 100))
        order_imp = lost / (lost + 1.0) * 100
        transit   = max(0.0, min(delay / 72.0 * 100, 100))
        ext       = max(0.0, min(downtime / 168.0 * 100, 100))

        proxy_indices.append(
            weights["shortage_urgency"] * shortage
            + weights["order_importance"] * order_imp
            + weights["transit_delay"] * transit
            + weights["external_event"] * ext
        )

    n = len(proxy_indices)
    if n < 5:
        return {
            "value": expert_trigger,
            "_source": "expert",
            "_sample_size": n,
            "_method": "expert_yaml",
            "_note": (
                f"失败/部分失败样本不足（{n} < 5），"
                f"使用专家默认阈值 {expert_trigger}"
            ),
        }

    threshold = round(_percentile(proxy_indices, 0.25), 1)
    return {
        "value": threshold,
        "_source": "calibrated",
        "_sample_size": n,
        "_method": "p25_failure_proxy_risk_index",
        "_note": (
            f"基于 {n} 条失败/部分失败记录的 P25 计算"
            f"（替代专家默认值 {expert_trigger}），召回率约 75%"
        ),
    }
