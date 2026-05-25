"""Future calibration hooks for ChainGuard enterprise deployment.

The MVP intentionally avoids machine learning and real enterprise system
connections. These functions define stable extension points for a later phase
where ERP/WMS/TMS exports can be used to fit weights, thresholds, and decision
scoring rules.
"""

from typing import Any

from src.config_loader import load_risk_weights, load_thresholds


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


def calibrate_inventory_risk_weights(historical_data: Any) -> dict[str, float]:
    """Return inventory risk weights for the current MVP.

    Future implementation:
    Fit inventory risk index weights from historical inventory snapshots,
    customer order delays, production downtime, shortage incidents, and
    financial impact records.

    Current implementation:
    Return the default expert weights from config/risk_weights.yaml. The
    historical_data argument is accepted to keep the future interface stable.
    """
    _ = historical_data
    return load_risk_weights()["inventory_risk_weights"]


def calibrate_thresholds(historical_data: Any) -> dict[str, Any]:
    """Return alert thresholds for the current MVP.

    Future implementation:
    Calibrate yellow warning, red warning, and inventory risk trigger thresholds
    from historical shortage incidents and emergency-response outcomes.

    Current implementation:
    Return the default expert thresholds from config/thresholds.yaml. The
    historical_data argument is accepted to keep the future interface stable.
    """
    _ = historical_data
    return load_thresholds()


def evaluate_decision_outcomes(historical_decisions: Any) -> dict[str, Any]:
    """Return a mock evaluation summary for historical decisions.

    Future implementation:
    Evaluate response strategies using actual emergency cost, delivery delay,
    production downtime, lost orders, customer complaints, and final outcome
    labels.

    Current implementation:
    Return a deterministic simulated result for demo and testing purposes.
    """
    _ = historical_decisions
    return {
        "status": "simulated",
        "sample_size": 0,
        "average_score": 82,
        "success_rate": 0.76,
        "key_findings": [
            "高优先级订单的库存锁定策略通常能降低延期风险。",
            "空运补货可提升时效，但需要结合成本和毛利约束评估。",
            "供应商可靠性评分应纳入应急采购方案排序。",
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
