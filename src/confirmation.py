from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIRMATION_LOG = "data/confirmation_log.jsonl"

ROLE_KEYWORDS: dict[str, str] = {
    "供应商": "采购",
    "采购": "采购",
    "补货": "采购",
    "运输": "物流",
    "空运": "物流",
    "交期": "物流",
    "路线": "物流",
    "成本": "财务",
    "毛利": "财务",
    "违约": "财务",
    "客户": "财务",
}
DEFAULT_ROLE = "供应链经理"


@dataclass(frozen=True)
class ConfirmationItem:
    point: str
    role: str
    risk_if_skipped: str


@dataclass(frozen=True)
class GateResult:
    total: int
    confirmed: int
    can_execute: bool
    blocked_points: list[str] = field(default_factory=list)
    override: bool = False


def assign_role(point: str) -> str:
    """按 ROLE_KEYWORDS 命中判定责任角色；无命中 → DEFAULT_ROLE。"""
    for keyword, role in ROLE_KEYWORDS.items():
        if keyword in point:
            return role
    return DEFAULT_ROLE


def build_confirmation_items(manual_points: list[str]) -> list[ConfirmationItem]:
    """把仲裁产出的确认点文本结构化为 (point, role, risk)。"""
    items: list[ConfirmationItem] = []
    for point in manual_points:
        role = assign_role(point)
        items.append(
            ConfirmationItem(
                point=point,
                role=role,
                risk_if_skipped=(
                    f"未确认即执行：若该项与实际不符，{role}需承担对应执行风险。"
                ),
            )
        )
    return items


def evaluate_gate(
    items: list[ConfirmationItem],
    confirmed_flags: dict[str, bool],
    *,
    override: bool = False,
    override_reason: str = "",
) -> GateResult:
    """判定能否放行：全部确认 → can_execute=True；override=True 且有理由 → 也放行。"""
    confirmed = sum(1 for it in items if confirmed_flags.get(it.point, False))
    blocked_points = [
        it.point for it in items if not confirmed_flags.get(it.point, False)
    ]
    can_execute = len(blocked_points) == 0 or (
        override is True and bool(override_reason.strip())
    )
    return GateResult(
        total=len(items),
        confirmed=confirmed,
        can_execute=can_execute,
        blocked_points=blocked_points,
        override=override,
    )


def record_confirmation(
    decision_id: str,
    items: list[ConfirmationItem],
    confirmed_flags: dict[str, bool],
    *,
    confirmed_by: str,
    override: bool = False,
    override_reason: str = "",
    path: str | Path = DEFAULT_CONFIRMATION_LOG,
) -> dict[str, Any]:
    """把本次确认/放行写入 JSONL，返回写入的记录 dict。"""
    gate = evaluate_gate(
        items,
        confirmed_flags,
        override=override,
        override_reason=override_reason,
    )
    record: dict[str, Any] = {
        "decision_id": decision_id,
        "confirmed_by": confirmed_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "override": override,
        "override_reason": override_reason,
        "items": [
            {
                "point": item.point,
                "role": item.role,
                "confirmed": confirmed_flags.get(item.point, False),
            }
            for item in items
        ],
        "can_execute": gate.can_execute,
    }

    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
