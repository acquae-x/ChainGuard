from dataclasses import dataclass, field

from src.audit import RISK_APPROVAL_THRESHOLD


@dataclass(frozen=True)
class AutomationSummary:
    total: int
    auto_approved: int
    escalated: int
    automation_rate: float
    escalation_rate: float
    escalation_reasons: dict[str, int] = field(default_factory=dict)


def summarize_automation(audit_entries: list[dict]) -> AutomationSummary:
    """从审计条目（dict 列表，AuditEntry.to_dict 形态）聚合自动化分工统计。"""
    total = len(audit_entries)
    escalated = sum(
        1 for entry in audit_entries if bool(entry["human_approval_required"])
    )
    auto_approved = total - escalated

    reasons: dict[str, int] = {}
    for entry in audit_entries:
        if not bool(entry["human_approval_required"]):
            continue

        risk_index = float(entry.get("inventory_risk_index", 0) or 0.0)
        debate_converged = entry.get("debate_converged", True)
        feasible_count = int(entry.get("constraint_feasible_count", 1) or 0)

        if risk_index > RISK_APPROVAL_THRESHOLD:
            reasons["高风险"] = reasons.get("高风险", 0) + 1
        if debate_converged is False:
            reasons["辩论未收敛"] = reasons.get("辩论未收敛", 0) + 1
        if feasible_count == 0:
            reasons["无可行解"] = reasons.get("无可行解", 0) + 1

    if total == 0:
        automation_rate = 0.0
        escalation_rate = 0.0
    else:
        automation_rate = round(auto_approved / total, 4)
        escalation_rate = round(escalated / total, 4)

    return AutomationSummary(
        total=total,
        auto_approved=auto_approved,
        escalated=escalated,
        automation_rate=automation_rate,
        escalation_rate=escalation_rate,
        escalation_reasons=reasons,
    )
