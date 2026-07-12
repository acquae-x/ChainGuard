from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


DEFAULT_KEY_FIELDS: tuple[str, ...] = (
    "event_type",
    "affected_material_id",
    "affected_supplier_id",
)
ROUTINE_THRESHOLD: int = 3
OCCASIONAL_THRESHOLD: int = 1


@dataclass(frozen=True)
class IntakeAssessment:
    signature: str
    seen_count: int
    familiarity: str
    requires_confirmation: bool
    confirmation_points: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass(frozen=True)
class IntakeReviewReport:
    total: int
    auto_passed: int
    needs_confirmation: int
    novel_count: int
    occasional_count: int
    routine_count: int
    assessments: list[IntakeAssessment] = field(default_factory=list)
    threshold_source: str = "default"


def _normalize_signature_value(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    return text or "unknown"


def signature_of(
    record: dict[str, Any],
    key_fields: Sequence[str] = DEFAULT_KEY_FIELDS,
) -> str:
    """由 key_fields 拼成归一化签名；缺字段以 'unknown' 占位。"""
    return "|".join(_normalize_signature_value(record.get(field)) for field in key_fields)


def build_history_counts(
    records: Iterable[dict[str, Any]],
    key_fields: Sequence[str] = DEFAULT_KEY_FIELDS,
) -> dict[str, int]:
    """统计历史记录中各签名出现次数。"""
    counts: dict[str, int] = {}
    for record in records:
        signature = signature_of(record, key_fields)
        counts[signature] = counts.get(signature, 0) + 1
    return counts


def calibrate_intake_thresholds(
    history_counts: dict[str, int],
) -> tuple[int, int]:
    """从历史频次分布推导 (routine_threshold, occasional_threshold)。

    这是 rule-based 百分位校准：有效签名不足时回退模块常量。
    """
    counts = sorted(count for count in history_counts.values() if count > 0)
    n = len(counts)
    if n < 5:
        return ROUTINE_THRESHOLD, OCCASIONAL_THRESHOLD

    routine = int(counts[int(n * 0.75)])
    occasional = int(counts[int(n * 0.25)])
    occasional = max(1, occasional)
    routine = max(routine, occasional + 1)
    return routine, occasional


def assess_intake(
    record: dict[str, Any],
    history_counts: dict[str, int],
    key_fields: Sequence[str] = DEFAULT_KEY_FIELDS,
    *,
    routine_threshold: int = ROUTINE_THRESHOLD,
    occasional_threshold: int = OCCASIONAL_THRESHOLD,
) -> IntakeAssessment:
    """Rule-based 单条复核：按精确签名历史频次判定确认要求。"""
    signature = signature_of(record, key_fields)
    seen = int(history_counts.get(signature, 0) or 0)

    if seen >= routine_threshold:
        return IntakeAssessment(
            signature=signature,
            seen_count=seen,
            familiarity="routine",
            requires_confirmation=False,
            confirmation_points=[],
            reason=f"历史已出现 {seen} 次，属常规需求，自动通过。",
        )

    if seen == 0:
        return IntakeAssessment(
            signature=signature,
            seen_count=seen,
            familiarity="novel",
            requires_confirmation=True,
            confirmation_points=[
                "首次出现的需求，请核对供应商资质与可供量。",
                "请核对需求量、交期与成本是否在合理区间。",
                "请确认该数据来源可信（ERP/WMS 导出无误）。",
            ],
            reason="历史无相同记录，首次出现，需完整人工确认。",
        )

    return IntakeAssessment(
        signature=signature,
        seen_count=seen,
        familiarity="occasional",
        requires_confirmation=True,
        confirmation_points=["请确认本次需求量与历史是否一致。"],
        reason=f"历史出现 {seen} 次，偶发需求，需轻量确认。",
    )


def review_batch(
    records: Sequence[dict[str, Any]],
    history_counts: dict[str, int],
    key_fields: Sequence[str] = DEFAULT_KEY_FIELDS,
    *,
    routine_threshold: int = ROUTINE_THRESHOLD,
    occasional_threshold: int = OCCASIONAL_THRESHOLD,
) -> IntakeReviewReport:
    """Rule-based 批量复核，输出自动通过 / 需确认汇总。"""
    assessments = [
        assess_intake(
            record,
            history_counts,
            key_fields,
            routine_threshold=routine_threshold,
            occasional_threshold=occasional_threshold,
        )
        for record in records
    ]
    auto_passed = sum(1 for item in assessments if not item.requires_confirmation)
    needs_confirmation = len(assessments) - auto_passed
    novel_count = sum(1 for item in assessments if item.familiarity == "novel")
    occasional_count = sum(
        1 for item in assessments if item.familiarity == "occasional"
    )
    routine_count = sum(1 for item in assessments if item.familiarity == "routine")
    threshold_source = (
        "default"
        if (
            routine_threshold == ROUTINE_THRESHOLD
            and occasional_threshold == OCCASIONAL_THRESHOLD
        )
        else "calibrated"
    )

    return IntakeReviewReport(
        total=len(assessments),
        auto_passed=auto_passed,
        needs_confirmation=needs_confirmation,
        novel_count=novel_count,
        occasional_count=occasional_count,
        routine_count=routine_count,
        assessments=assessments,
        threshold_source=threshold_source,
    )
